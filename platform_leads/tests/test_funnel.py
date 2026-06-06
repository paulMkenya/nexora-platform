"""Platform-owner sales funnel — public capture form + owner-only pipeline.

Covers the spec's required checks:
  * public form submits + creates a PlatformLead (each lead_type)
  * honeypot + per-IP rate limit reject spam (no record / 429)
  * owner notification is sent to the configured address, fail-safe (a send
    failure is swallowed and the form still succeeds)
  * pipeline is STRICTLY superuser-only (brand admin + affiliate manager 403,
    anon redirected; no "Sales Funnel" nav link for non-owners)
  * manual stage change + notes + mark-contacted work
  * required-field validation; adaptive/qualifying fields optional server-side
"""
from unittest import mock

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.test import TestCase

from brands.models import Brand
from offer.models import Category, TrafficSource
from platform_leads import views
from platform_leads.models import PlatformLead
from project._celery import _celery
from user_profile.models import Profile

User = get_user_model()


def _min_post(lead_type='NETWORK', **extra):
    data = {'lead_type': lead_type, 'name': 'Pat Prospect', 'email': 'pat@prospect.test'}
    data.update(extra)
    return data


class FunnelBase(TestCase):
    def setUp(self):
        # Inline Celery so the async owner-alert path runs deterministically,
        # and don't re-raise (mirror the real fail-safe dispatch).
        self._eager = _celery.conf.task_always_eager
        self._prop = _celery.conf.task_eager_propagates
        _celery.conf.task_always_eager = True
        _celery.conf.task_eager_propagates = False
        # LocMemCache persists across tests in one process; start each test clean
        # so rate-limit counters don't leak between cases.
        cache.clear()

        self.brand = Brand.objects.create(
            slug='a', name='Brand A', primary_domain='a.test',
            tracking_domain='t.a.test', is_default=True,
            owner_sales_notification_email='sales@platform.test')

        self.owner = User.objects.create_superuser('owner', 'owner@test.com', 'pass')
        self.admin = User.objects.create_user('admin_a', email='admin_a@a.test',
                                               password='pass', is_staff=True)
        self.admin.profile.role = Profile.Role.NETWORK_ADMIN
        self.admin.profile.brand = self.brand
        self.admin.profile.save()
        self.mgr = User.objects.create_user('mgr_a', password='pass')
        self.mgr.profile.role = Profile.Role.AFFILIATE_MANAGER
        self.mgr.profile.brand = self.brand
        self.mgr.profile.save()

    def tearDown(self):
        _celery.conf.task_always_eager = self._eager
        _celery.conf.task_eager_propagates = self._prop


# ── Public capture form ──────────────────────────────────────────────────────

class PublicFormTest(FunnelBase):
    def test_get_renders_form(self):
        resp = self.client.get('/get-started/', HTTP_HOST='a.test')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Request your network')

    def test_submit_creates_lead_each_type(self):
        for lt, _label in PlatformLead.LeadType.choices:
            mail.outbox = []
            resp = self.client.post('/get-started/', _min_post(lt, email=f'{lt}@x.test'),
                                    HTTP_HOST='a.test')
            self.assertEqual(resp.status_code, 200)
            self.assertContains(resp, "we'll be in touch")
            lead = PlatformLead.objects.get(email=f'{lt}@x.test')
            self.assertEqual(lead.lead_type, lt)
            self.assertEqual(lead.sales_stage, PlatformLead.Stage.NEW)

    def test_qualifying_fields_optional_but_captured(self):
        cat = Category.objects.first()
        ts = TrafficSource.objects.first()
        resp = self.client.post('/get-started/', _min_post(
            'ADVERTISER', email='rich@x.test', phone='+254700000000',
            company='RichCo', country='ke', website='https://richco.test',
            scale='100k clicks/mo', pain='Outgrew our tracker', timeline='SOON',
            budget='$5k', source='Google', verticals=[str(cat.id)],
            traffic_sources=[str(ts.id)],
        ), HTTP_HOST='a.test')
        self.assertEqual(resp.status_code, 200)
        lead = PlatformLead.objects.get(email='rich@x.test')
        self.assertEqual(lead.country, 'KE')
        self.assertEqual(lead.timeline, 'SOON')
        self.assertEqual(list(lead.verticals.all()), [cat])
        self.assertEqual(list(lead.traffic_sources.all()), [ts])

    def test_only_required_fields_succeeds(self):
        resp = self.client.post('/get-started/', _min_post(), HTTP_HOST='a.test')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(PlatformLead.objects.count(), 1)

    def test_missing_required_fields_rejected(self):
        # No name/email/type → validation error, no record.
        resp = self.client.post('/get-started/', {'lead_type': 'OTHER'}, HTTP_HOST='a.test')
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(PlatformLead.objects.count(), 0)

    def test_invalid_lead_type_rejected(self):
        resp = self.client.post('/get-started/',
                                _min_post('BOGUS'), HTTP_HOST='a.test')
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(PlatformLead.objects.count(), 0)

    def test_honeypot_drops_spam_silently(self):
        resp = self.client.post('/get-started/',
                                _min_post(company_url='http://spam.test'),
                                HTTP_HOST='a.test')
        self.assertEqual(resp.status_code, 200)          # looks fine to the bot
        self.assertEqual(PlatformLead.objects.count(), 0)  # but nothing stored

    def test_rate_limit_blocks_after_budget(self):
        # RATE_LIMIT_MAX submissions allowed, the next is 429.
        for i in range(views.RATE_LIMIT_MAX):
            r = self.client.post('/get-started/', _min_post(email=f'r{i}@x.test'),
                                 HTTP_HOST='a.test')
            self.assertEqual(r.status_code, 200)
        blocked = self.client.post('/get-started/', _min_post(email='over@x.test'),
                                   HTTP_HOST='a.test')
        self.assertEqual(blocked.status_code, 429)
        self.assertFalse(PlatformLead.objects.filter(email='over@x.test').exists())


# ── Owner notification ───────────────────────────────────────────────────────

class NotificationTest(FunnelBase):
    def test_owner_alert_sent_to_configured_address(self):
        mail.outbox = []
        self.client.post('/get-started/', _min_post(company='BigNet'), HTTP_HOST='a.test')
        recipients = [a for m in mail.outbox for a in m.to]
        self.assertIn('sales@platform.test', recipients)
        alert = [m for m in mail.outbox if 'sales@platform.test' in m.to][0]
        self.assertIn('New platform lead', alert.subject)
        self.assertIn('BigNet', alert.body)
        self.assertIn('/admin/platform-leads/', alert.body)

    def test_owner_alert_uses_resolver_fallback_when_blank(self):
        self.brand.owner_sales_notification_email = ''
        self.brand.save(update_fields=['owner_sales_notification_email'])
        # No ADMIN_EMAIL setting in tests → falls back to first superuser email.
        self.assertEqual(Brand.owner_sales_recipient(), 'owner@test.com')

    def test_notification_failure_is_swallowed(self):
        with mock.patch('platform_leads.tasks.send_brand_mail',
                        side_effect=RuntimeError('smtp down')):
            resp = self.client.post('/get-started/', _min_post(email='robust@x.test'),
                                    HTTP_HOST='a.test')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(PlatformLead.objects.filter(email='robust@x.test').exists())


# ── Owner-only pipeline access ───────────────────────────────────────────────

class PipelineAccessTest(FunnelBase):
    def setUp(self):
        super().setUp()
        self.lead = PlatformLead.objects.create(
            lead_type='NETWORK', name='Acme', email='acme@x.test')

    def test_owner_sees_pipeline(self):
        self.client.force_login(self.owner)
        resp = self.client.get('/admin/platform-leads/', HTTP_HOST='a.test')
        self.assertEqual(resp.status_code, 200)
        self.assertIn(self.lead, list(resp.context['leads']))

    def test_brand_admin_forbidden(self):
        self.client.force_login(self.admin)
        resp = self.client.get('/admin/platform-leads/', HTTP_HOST='a.test')
        self.assertEqual(resp.status_code, 403)

    def test_affiliate_manager_forbidden(self):
        self.client.force_login(self.mgr)
        resp = self.client.get('/admin/platform-leads/', HTTP_HOST='a.test')
        self.assertEqual(resp.status_code, 403)

    def test_anonymous_redirected(self):
        resp = self.client.get('/admin/platform-leads/', HTTP_HOST='a.test')
        self.assertNotEqual(resp.status_code, 200)  # login_required → 302

    def test_brand_admin_detail_forbidden(self):
        self.client.force_login(self.admin)
        resp = self.client.get(f'/admin/platform-leads/{self.lead.pk}/', HTTP_HOST='a.test')
        self.assertEqual(resp.status_code, 403)

    def test_brand_admin_stage_change_forbidden(self):
        self.client.force_login(self.admin)
        resp = self.client.post(f'/admin/platform-leads/{self.lead.pk}/stage/',
                                {'sales_stage': 'WON'}, HTTP_HOST='a.test')
        self.assertEqual(resp.status_code, 403)
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.sales_stage, 'NEW')

    def test_nav_link_owner_only(self):
        # Owner sees the Sales Funnel nav link...
        self.client.force_login(self.owner)
        resp = self.client.get('/admin/dashboard/', HTTP_HOST='a.test')
        self.assertContains(resp, '/admin/platform-leads/')
        # ...the brand admin does not.
        self.client.force_login(self.admin)
        resp = self.client.get('/admin/dashboard/', HTTP_HOST='a.test')
        self.assertNotContains(resp, '/admin/platform-leads/')


# ── Owner pipeline actions ───────────────────────────────────────────────────

class PipelineActionsTest(FunnelBase):
    def setUp(self):
        super().setUp()
        self.lead = PlatformLead.objects.create(
            lead_type='NETWORK', name='Acme', email='acme@x.test')
        self.client.force_login(self.owner)

    def test_manual_stage_change(self):
        self.client.post(f'/admin/platform-leads/{self.lead.pk}/stage/',
                         {'sales_stage': 'QUALIFIED'}, HTTP_HOST='a.test')
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.sales_stage, 'QUALIFIED')

    def test_invalid_stage_ignored(self):
        self.client.post(f'/admin/platform-leads/{self.lead.pk}/stage/',
                         {'sales_stage': 'NONSENSE'}, HTTP_HOST='a.test')
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.sales_stage, 'NEW')

    def test_add_note(self):
        self.client.post(f'/admin/platform-leads/{self.lead.pk}/note/',
                         {'note': 'Left a voicemail'}, HTTP_HOST='a.test')
        self.lead.refresh_from_db()
        self.assertIn('Left a voicemail', self.lead.notes)

    def test_mark_contacted(self):
        self.assertIsNone(self.lead.last_contact_at)
        self.client.post(f'/admin/platform-leads/{self.lead.pk}/contacted/',
                         HTTP_HOST='a.test')
        self.lead.refresh_from_db()
        self.assertIsNotNone(self.lead.last_contact_at)

    def test_settings_saves_notification_email(self):
        self.client.post('/admin/platform-leads/settings/',
                         {'owner_sales_notification_email': 'new@desk.test'},
                         HTTP_HOST='a.test', follow=True)
        self.brand.refresh_from_db()
        self.assertEqual(self.brand.owner_sales_notification_email, 'new@desk.test')

    def test_settings_owner_only(self):
        self.client.force_login(self.admin)
        resp = self.client.get('/admin/platform-leads/settings/', HTTP_HOST='a.test')
        self.assertEqual(resp.status_code, 403)
