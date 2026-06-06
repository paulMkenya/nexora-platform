"""Brand-scoped CRM lead pipeline + corrected registration notifications.

Two-brand fixture throughout. Covers:
  * affiliate registration → NEW lead, NO operator notification
  * advertiser registration → NEW lead, notifies the brand notification email
    ONLY (never the platform owner)
  * stage auto-advance: verify→VERIFIED, approve→APPROVED, activity→ACTIVATED
  * dormancy beat task → DORMANT
  * brand-scoped pipeline view: brand admin own-brand only (list + 404 by id),
    owner sees all, affiliate manager blocked
  * notification failure is swallowed (registration still succeeds)
  * notification recipient read from the brand setting; blank skipped
  * idempotency (one lead per entity)
"""
from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.utils import timezone

from brands.models import Brand
from leads.models import Lead
from leads.services import sync_from_profile
from leads.tasks import mark_dormant_leads
from offer.models import Advertiser, Offer
from project._celery import _celery
from tracker.models import Click
from user_profile.models import Profile

User = get_user_model()


def _brand(slug, notification_email=''):
    return Brand.objects.create(
        slug=slug, name=f'Brand {slug.upper()}',
        primary_domain=f'{slug}.test', tracking_domain=f't.{slug}.test',
        is_default=(slug == 'a'), notification_email=notification_email,
    )


def _user(username, role, brand=None, *, email='', is_staff=False, is_superuser=False):
    u = User.objects.create_user(username, email=email, password='pass',
                                 is_staff=is_staff, is_superuser=is_superuser)
    p = u.profile
    p.role = role
    p.brand = brand
    p.save()
    return u


def _affiliate(username, brand, *, status=Profile.AffiliateStatus.PENDING,
               email_verified=False, email=''):
    u = _user(username, Profile.Role.AFFILIATE, brand, email=email or f'{username}@aff.test')
    p = u.profile
    p.affiliate_status = status
    p.email_verified = email_verified
    p.save()
    return u


def _advertiser(company, brand, *, status=Advertiser.AdvertiserStatus.PENDING,
                email_verified=False):
    u = _user(f'adv_{company}', Profile.Role.ADVERTISER, brand,
              email=f'{company}@adv.test')
    adv = Advertiser.objects.create(
        user=u, company=company, email=f'{company}@adv.test', brand=brand,
        contact_person=company, advertiser_status=status,
        email_verified=email_verified)
    return u, adv


@override_settings(CACHES={'default': {'BACKEND': 'django.core.cache.backends.dummy.DummyCache'}})
class PipelineBase(TestCase):
    def setUp(self):
        # Run Celery tasks inline + don't re-raise, so the async notification
        # path is exercised deterministically without a broker.
        self._eager = _celery.conf.task_always_eager
        self._prop = _celery.conf.task_eager_propagates
        _celery.conf.task_always_eager = True
        _celery.conf.task_eager_propagates = False

        self.brand_a = _brand('a', notification_email='ops-a@a.test')
        self.brand_b = _brand('b', notification_email='ops-b@b.test')

        self.owner = User.objects.create_superuser('owner', 'owner@test.com', 'pass')
        self.owner.profile.role = Profile.Role.NETWORK_ADMIN
        self.owner.profile.save(update_fields=['role'])

        self.admin_a = _user('admin_a', Profile.Role.NETWORK_ADMIN, self.brand_a,
                             email='admin_a@a.test', is_staff=True)
        self.admin_b = _user('admin_b', Profile.Role.NETWORK_ADMIN, self.brand_b,
                             email='admin_b@b.test', is_staff=True)
        self.mgr_a = _user('mgr_a', Profile.Role.AFFILIATE_MANAGER, self.brand_a)

    def tearDown(self):
        _celery.conf.task_always_eager = self._eager
        _celery.conf.task_eager_propagates = self._prop


# ── Registration: tracking + corrected notifications ─────────────────────────

class RegistrationNotificationTest(PipelineBase):
    def test_affiliate_registration_creates_new_lead_and_no_operator_notification(self):
        mail.outbox = []
        resp = self.client.post('/partner/register/', {
            'first_name': 'Aff', 'last_name': 'Iliate',
            'email': 'newaff@x.test',
            'password1': 'sup3rsecret!pw', 'password2': 'sup3rsecret!pw',
        }, HTTP_HOST='a.test')
        self.assertEqual(resp.status_code, 302)

        user = User.objects.get(email='newaff@x.test')
        lead = Lead.objects.get(profile=user.profile)
        self.assertEqual(lead.lead_type, Lead.Type.AFFILIATE)
        self.assertEqual(lead.pipeline_stage, Lead.Stage.NEW)
        self.assertEqual(lead.brand, self.brand_a)

        # Only the registrant's own verification email — NO operator alert to the
        # brand notification address or the owner.
        recipients = [addr for m in mail.outbox for addr in m.to]
        self.assertIn('newaff@x.test', recipients)
        self.assertNotIn('ops-a@a.test', recipients)
        self.assertNotIn('owner@test.com', recipients)

    def test_advertiser_registration_creates_new_lead_and_notifies_brand_only(self):
        mail.outbox = []
        resp = self.client.post('/advertiser/register/', {
            'company': 'NewCo', 'contact_name': 'Jane Doe',
            'email': 'jane@newco.test',
            'password1': 'sup3rsecret!pw', 'password2': 'sup3rsecret!pw',
        }, HTTP_HOST='b.test')
        self.assertEqual(resp.status_code, 302)

        adv = User.objects.get(email='jane@newco.test').advertiser_profile
        lead = Lead.objects.get(advertiser=adv)
        self.assertEqual(lead.lead_type, Lead.Type.ADVERTISER)
        self.assertEqual(lead.pipeline_stage, Lead.Stage.NEW)
        self.assertEqual(lead.brand, self.brand_b)

        # The brand-B notification email is alerted; the owner is NOT.
        recipients = [addr for m in mail.outbox for addr in m.to]
        self.assertIn('ops-b@b.test', recipients)
        self.assertNotIn('owner@test.com', recipients)
        self.assertNotIn('ops-a@a.test', recipients)

        alert = [m for m in mail.outbox if 'ops-b@b.test' in m.to][0]
        self.assertIn('New advertiser registration', alert.subject)
        self.assertIn('NewCo', alert.body)
        self.assertIn('/admin/advertisers/', alert.body)

    def test_advertiser_notification_blank_recipient_skipped(self):
        # Brand with no notification_email AND no brand admin email → skip.
        Brand.objects.create(
            slug='c', name='Brand C', primary_domain='c.test',
            tracking_domain='t.c.test')
        mail.outbox = []
        resp = self.client.post('/advertiser/register/', {
            'company': 'Quiet', 'contact_name': 'No One',
            'email': 'quiet@c.test',
            'password1': 'sup3rsecret!pw', 'password2': 'sup3rsecret!pw',
        }, HTTP_HOST='c.test')
        self.assertEqual(resp.status_code, 302)
        recipients = [addr for m in mail.outbox for addr in m.to]
        # Registrant still gets their verification email; no operator alert.
        self.assertIn('quiet@c.test', recipients)
        self.assertFalse(any(s.subject.startswith('New advertiser registration')
                             for s in mail.outbox))

    def test_advertiser_notification_falls_back_to_brand_admin_email(self):
        brand_d = Brand.objects.create(
            slug='d', name='Brand D', primary_domain='d.test',
            tracking_domain='t.d.test')  # no notification_email
        _user('admin_d', Profile.Role.NETWORK_ADMIN, brand_d, email='admin_d@d.test')
        mail.outbox = []
        self.client.post('/advertiser/register/', {
            'company': 'FallCo', 'contact_name': 'Fall Back',
            'email': 'fall@d.test',
            'password1': 'sup3rsecret!pw', 'password2': 'sup3rsecret!pw',
        }, HTTP_HOST='d.test')
        recipients = [addr for m in mail.outbox for addr in m.to]
        self.assertIn('admin_d@d.test', recipients)

    def test_notification_failure_is_swallowed_registration_succeeds(self):
        with mock.patch('leads.tasks.send_brand_mail', side_effect=RuntimeError('smtp down')):
            resp = self.client.post('/advertiser/register/', {
                'company': 'Robust', 'contact_name': 'Still Works',
                'email': 'robust@b.test',
                'password1': 'sup3rsecret!pw', 'password2': 'sup3rsecret!pw',
            }, HTTP_HOST='b.test')
        self.assertEqual(resp.status_code, 302)
        adv = User.objects.get(email='robust@b.test').advertiser_profile
        self.assertTrue(Lead.objects.filter(advertiser=adv).exists())


# ── Auto-advancing stages ────────────────────────────────────────────────────

class StageTransitionTest(PipelineBase):
    def test_registration_is_new(self):
        u = _affiliate('s_new', self.brand_a)
        self.assertEqual(Lead.objects.get(profile=u.profile).pipeline_stage,
                         Lead.Stage.NEW)

    def test_email_verification_advances_to_verified(self):
        from affiliate_ui.views.registration_views import _make_token
        u = _affiliate('s_ver', self.brand_a)
        token = _make_token(u.pk)
        resp = self.client.get(f'/partner/verify-email/{token}/', HTTP_HOST='a.test')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Lead.objects.get(profile=u.profile).pipeline_stage,
                         Lead.Stage.VERIFIED)

    def test_brand_admin_approval_advances_to_approved(self):
        u = _affiliate('s_app', self.brand_a, email_verified=True)
        self.client.force_login(self.admin_a)
        resp = self.client.post(f'/admin/affiliates/{u.profile.pk}/approve/',
                                HTTP_HOST='a.test')
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(Lead.objects.get(profile=u.profile).pipeline_stage,
                         Lead.Stage.APPROVED)

    def test_advertiser_approval_advances_to_approved(self):
        _, adv = _advertiser('AppCo', self.brand_a, email_verified=True)
        self.client.force_login(self.admin_a)
        resp = self.client.post(f'/admin/advertisers/{adv.pk}/approve/',
                                HTTP_HOST='a.test')
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(Lead.objects.get(advertiser=adv).pipeline_stage,
                         Lead.Stage.APPROVED)

    def test_affiliate_first_click_advances_to_activated(self):
        u = _affiliate('s_act', self.brand_a,
                       status=Profile.AffiliateStatus.APPROVED, email_verified=True)
        Click.objects.create(
            offer=None, affiliate=u, brand=self.brand_a, ip='1.2.3.4',
            revenue=0, payout=0)
        lead = Lead.objects.get(profile=u.profile)
        self.assertEqual(lead.pipeline_stage, Lead.Stage.ACTIVATED)
        self.assertIsNotNone(lead.last_activity_at)

    def test_advertiser_first_offer_advances_to_activated(self):
        _, adv = _advertiser('OffCo', self.brand_a,
                             status=Advertiser.AdvertiserStatus.APPROVED,
                             email_verified=True)
        Offer.objects.create(title='O1', advertiser=adv, brand=self.brand_a)
        lead = Lead.objects.get(advertiser=adv)
        self.assertEqual(lead.pipeline_stage, Lead.Stage.ACTIVATED)
        self.assertIsNotNone(lead.last_activity_at)

    def test_dormancy_task_marks_idle_activated_leads(self):
        u = _affiliate('s_dorm', self.brand_a,
                       status=Profile.AffiliateStatus.APPROVED, email_verified=True)
        Click.objects.create(offer=None, affiliate=u, brand=self.brand_a,
                             ip='1.2.3.4', revenue=0, payout=0)
        lead = Lead.objects.get(profile=u.profile)
        self.assertEqual(lead.pipeline_stage, Lead.Stage.ACTIVATED)
        # Make it idle beyond the threshold.
        Lead.objects.filter(pk=lead.pk).update(
            last_activity_at=timezone.now() - timedelta(days=40))

        with override_settings(LEADS_DORMANT_DAYS=30):
            updated = mark_dormant_leads()
        self.assertEqual(updated, 1)
        lead.refresh_from_db()
        self.assertEqual(lead.pipeline_stage, Lead.Stage.DORMANT)


# ── Brand-scoped operator pipeline view ──────────────────────────────────────

class PipelineViewScopingTest(PipelineBase):
    def setUp(self):
        super().setUp()
        self.aff_a = _affiliate('view_a', self.brand_a)
        self.aff_b = _affiliate('view_b', self.brand_b)
        self.lead_a = Lead.objects.get(profile=self.aff_a.profile)
        self.lead_b = Lead.objects.get(profile=self.aff_b.profile)

    def test_brand_admin_sees_only_own_brand_leads(self):
        self.client.force_login(self.admin_a)
        resp = self.client.get('/admin/leads/', HTTP_HOST='a.test')
        self.assertEqual(resp.status_code, 200)
        ids = {lead.pk for lead in resp.context['leads']}
        self.assertIn(self.lead_a.pk, ids)
        self.assertNotIn(self.lead_b.pk, ids)

    def test_brand_admin_cross_brand_lead_is_404(self):
        self.client.force_login(self.admin_a)
        resp = self.client.post(f'/admin/leads/{self.lead_b.pk}/stage/',
                                {'pipeline_stage': 'APPROVED'}, HTTP_HOST='a.test')
        self.assertEqual(resp.status_code, 404)
        self.lead_b.refresh_from_db()
        self.assertEqual(self.lead_b.pipeline_stage, Lead.Stage.NEW)

    def test_owner_sees_all_brands(self):
        self.client.force_login(self.owner)
        resp = self.client.get('/admin/leads/', HTTP_HOST='a.test')
        self.assertEqual(resp.status_code, 200)
        ids = {lead.pk for lead in resp.context['leads']}
        self.assertIn(self.lead_a.pk, ids)
        self.assertIn(self.lead_b.pk, ids)

    def test_affiliate_manager_blocked(self):
        self.client.force_login(self.mgr_a)
        resp = self.client.get('/admin/leads/', HTTP_HOST='a.test')
        self.assertEqual(resp.status_code, 403)

    def test_stage_filter(self):
        Lead.objects.filter(pk=self.lead_a.pk).update(pipeline_stage='APPROVED')
        self.client.force_login(self.owner)
        resp = self.client.get('/admin/leads/?stage=APPROVED', HTTP_HOST='a.test')
        ids = {lead.pk for lead in resp.context['leads']}
        self.assertIn(self.lead_a.pk, ids)
        self.assertNotIn(self.lead_b.pk, ids)

    def test_stage_counts_present(self):
        self.client.force_login(self.admin_a)
        resp = self.client.get('/admin/leads/', HTTP_HOST='a.test')
        counts = {c['value']: c['count'] for c in resp.context['stage_counts']}
        self.assertEqual(counts['NEW'], 1)  # only brand-a's lead
        self.assertEqual(set(counts), set(dict(Lead.Stage.choices)))

    def test_manual_stage_change_and_note(self):
        self.client.force_login(self.admin_a)
        self.client.post(f'/admin/leads/{self.lead_a.pk}/stage/',
                         {'pipeline_stage': 'DORMANT'}, HTTP_HOST='a.test')
        self.client.post(f'/admin/leads/{self.lead_a.pk}/note/',
                         {'note': 'called them'}, HTTP_HOST='a.test')
        self.lead_a.refresh_from_db()
        self.assertEqual(self.lead_a.pipeline_stage, Lead.Stage.DORMANT)
        self.assertIn('called them', self.lead_a.notes)


# ── Idempotency ──────────────────────────────────────────────────────────────

class IdempotencyTest(PipelineBase):
    def test_repeated_sync_keeps_one_lead(self):
        u = _affiliate('idem', self.brand_a)
        sync_from_profile(u.profile)
        sync_from_profile(u.profile)
        u.profile.save()  # fires the signal again
        self.assertEqual(Lead.objects.filter(profile=u.profile).count(), 1)


# ── Notification recipient read from the brand setting (UI) ──────────────────

class EmailSettingsNotificationTest(PipelineBase):
    def test_email_settings_page_saves_notification_email(self):
        self.client.force_login(self.admin_a)
        resp = self.client.post('/admin/brands/email-settings/', {
            'action': 'save',
            'smtp_from_email': '', 'smtp_host': '', 'smtp_port': '587',
            'smtp_username': '', 'smtp_password': '',
            'notification_email': 'changed@a.test',
        }, HTTP_HOST='a.test', follow=True)
        self.assertEqual(resp.status_code, 200)
        self.brand_a.refresh_from_db()
        self.assertEqual(self.brand_a.notification_email, 'changed@a.test')

    def test_recipient_used_for_advertiser_alert(self):
        self.brand_a.notification_email = 'desk@a.test'
        self.brand_a.save(update_fields=['notification_email'])
        mail.outbox = []
        self.client.post('/advertiser/register/', {
            'company': 'AlertCo', 'contact_name': 'A B',
            'email': 'alertco@a.test',
            'password1': 'sup3rsecret!pw', 'password2': 'sup3rsecret!pw',
        }, HTTP_HOST='a.test')
        recipients = [addr for m in mail.outbox for addr in m.to]
        self.assertIn('desk@a.test', recipients)


# ── Backfill (migration data logic) ──────────────────────────────────────────

class BackfillTest(PipelineBase):
    """Exercise the migration's backfill helper.

    Entities are created (the live signal makes their leads), the leads are then
    wiped to simulate a pre-migration database, and the backfill is run to prove
    it derives sensible stages from each entity's current state.
    """
    def test_backfill_derives_sensible_stages(self):
        from leads.migrations import import_backfill

        new_u = _affiliate('bf_new', self.brand_a)
        ver_u = _affiliate('bf_ver', self.brand_a, email_verified=True)
        app_u = _affiliate('bf_app', self.brand_a,
                           status=Profile.AffiliateStatus.APPROVED,
                           email_verified=True)
        act_u = _affiliate('bf_act', self.brand_a,
                           status=Profile.AffiliateStatus.APPROVED,
                           email_verified=True)
        Click.objects.create(offer=None, affiliate=act_u, brand=self.brand_a,
                             ip='1.1.1.1', revenue=0, payout=0)
        _, adv = _advertiser('BfAdv', self.brand_a,
                             status=Advertiser.AdvertiserStatus.APPROVED,
                             email_verified=True)

        # Simulate a pre-migration DB: no leads exist yet.
        Lead.objects.all().delete()
        import_backfill()

        self.assertEqual(Lead.objects.get(profile=new_u.profile).pipeline_stage, 'NEW')
        self.assertEqual(Lead.objects.get(profile=ver_u.profile).pipeline_stage, 'VERIFIED')
        self.assertEqual(Lead.objects.get(profile=app_u.profile).pipeline_stage, 'APPROVED')
        self.assertEqual(Lead.objects.get(profile=act_u.profile).pipeline_stage, 'ACTIVATED')
        # Approved + verified advertiser with no offers → APPROVED.
        self.assertEqual(Lead.objects.get(advertiser=adv).pipeline_stage, 'APPROVED')

    def test_backfill_is_idempotent(self):
        from leads.migrations import import_backfill
        _affiliate('bf_idem', self.brand_a)  # signal already made its lead
        before = Lead.objects.count()
        import_backfill()
        self.assertEqual(Lead.objects.count(), before)

