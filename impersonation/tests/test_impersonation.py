"""Impersonation: scope, abuse cases, money block, audit log, live re-validation.

Security-critical. The scope checks reuse the existing object-level console
scoping; these tests pin every downward/sideways/upward/archived case, the
server-side money block, the audit trail, per-request re-validation, and the
no-nesting rule.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from brands.models import Brand
from impersonation.models import ImpersonationLog
from offer.models import Advertiser
from user_profile.models import Profile

User = get_user_model()


def _brand(slug, *, default=False):
    return Brand.objects.create(
        slug=slug, name=f'Brand {slug.upper()}',
        primary_domain=f'{slug}.test', tracking_domain=f't.{slug}.test',
        is_default=default,
    )


def _user(username, role, brand=None, *, is_staff=False):
    u = User.objects.create_user(username, password='pass', is_staff=is_staff)
    p = u.profile
    p.role = role
    p.brand = brand
    p.save()
    return u


def _affiliate(username, brand, *, archived=False):
    u = _user(username, Profile.Role.AFFILIATE, brand)
    p = u.profile
    p.affiliate_status = Profile.AffiliateStatus.APPROVED
    p.email_verified = True
    p.is_archived = archived
    p.save()
    return u


def _advertiser(username, brand, *, archived=False):
    u = _user(username, Profile.Role.ADVERTISER, brand)
    adv = Advertiser.objects.create(
        company=username, email=f'{username}@x.com', brand=brand, user=u,
        advertiser_status=Advertiser.AdvertiserStatus.APPROVED, email_verified=True,
        is_archived=archived,
    )
    return u, adv


@override_settings(PLATFORM_ADMIN_HOSTS=['testserver'])
class ImpersonationBase(TestCase):
    def setUp(self):
        self.brand_a = _brand('a', default=True)
        self.brand_b = _brand('b')

        self.owner = User.objects.create_superuser('owner', 'owner@test.com', 'pass')
        self.owner.profile.role = Profile.Role.NETWORK_ADMIN
        self.owner.profile.save(update_fields=['role'])

        self.admin_a = _user('admin_a', Profile.Role.NETWORK_ADMIN, self.brand_a, is_staff=True)
        self.admin_b = _user('admin_b', Profile.Role.NETWORK_ADMIN, self.brand_b, is_staff=True)
        self.mgr_a = _user('mgr_a', Profile.Role.AFFILIATE_MANAGER, self.brand_a)

        self.aff_a = _affiliate('aff_a', self.brand_a)
        self.aff_b = _affiliate('aff_b', self.brand_b)
        self.adv_a_user, self.adv_a = _advertiser('adv_a', self.brand_a)

    def _start(self, target_user):
        return self.client.post(f'/admin/impersonate/start/{target_user.pk}/')

    def _banner_present(self):
        """Fetch a target-reachable HTML page and report whether the banner shows."""
        r = self.client.get('/partner/dashboard/')
        return b'You are viewing as' in r.content


# ─────────────────────────── allowed (downward, in scope) ───────────────────

class AllowedImpersonationTest(ImpersonationBase):
    def test_owner_impersonates_affiliate_any_brand(self):
        self.client.force_login(self.owner)
        r = self._start(self.aff_b)  # brand B, different from default
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.client.session['impersonate_target_id'], self.aff_b.pk)
        self.assertTrue(self._banner_present())

    def test_brand_admin_impersonates_own_brand_affiliate(self):
        self.client.force_login(self.admin_a)
        r = self._start(self.aff_a)
        self.assertEqual(r.status_code, 302)
        self.assertTrue(self._banner_present())

    def test_brand_admin_impersonates_own_brand_advertiser(self):
        self.client.force_login(self.admin_a)
        r = self._start(self.adv_a_user)
        self.assertEqual(r.status_code, 302)
        self.assertTrue(self._banner_present())

    def test_return_restores_original_actor(self):
        self.client.force_login(self.admin_a)
        self._start(self.aff_a)
        self.assertTrue(self._banner_present())
        r = self.client.post('/admin/impersonate/stop/')
        self.assertEqual(r.status_code, 302)
        self.assertNotIn('impersonate_target_id', self.client.session)
        # Back to the actor: the operator console is reachable again, no banner.
        r2 = self.client.get('/admin/affiliates/')
        self.assertEqual(r2.status_code, 200)
        self.assertNotIn(b'You are viewing as', r2.content)


# ─────────────────────────── abuse cases (must reject) ──────────────────────

class AbuseImpersonationTest(ImpersonationBase):
    def test_brand_admin_cannot_impersonate_other_brand_user(self):
        self.client.force_login(self.admin_a)
        r = self._start(self.aff_b)  # brand B
        self.assertEqual(r.status_code, 404)
        self.assertNotIn('impersonate_target_id', self.client.session)

    def test_brand_admin_cannot_impersonate_another_brand_admin(self):
        self.client.force_login(self.admin_a)
        r = self._start(self.admin_b)
        self.assertEqual(r.status_code, 404)

    def test_brand_admin_cannot_impersonate_platform_owner(self):
        self.client.force_login(self.admin_a)
        r = self._start(self.owner)
        self.assertEqual(r.status_code, 404)

    def test_brand_admin_cannot_impersonate_self(self):
        self.client.force_login(self.admin_a)
        r = self._start(self.admin_a)
        self.assertEqual(r.status_code, 404)

    def test_cannot_impersonate_archived_user_via_post(self):
        arch = _affiliate('aff_arch', self.brand_a, archived=True)
        self.client.force_login(self.admin_a)
        r = self._start(arch)
        self.assertEqual(r.status_code, 404)
        self.assertNotIn('impersonate_target_id', self.client.session)

    def test_archived_user_has_no_login_as_button(self):
        arch = _affiliate('aff_arch2', self.brand_a, archived=True)
        self.client.force_login(self.admin_a)
        r = self.client.get('/admin/affiliates/')
        # The archived user's own start URL is absent (their row isn't listed)...
        self.assertNotContains(r, f'/admin/impersonate/start/{arch.pk}/')
        # ...while a live affiliate DOES expose the button.
        self.assertContains(r, f'/admin/impersonate/start/{self.aff_a.pk}/')

    def test_affiliate_manager_cannot_impersonate(self):
        self.client.force_login(self.mgr_a)
        r = self._start(self.aff_a)
        self.assertEqual(r.status_code, 403)

    def test_login_as_button_present_for_owner(self):
        self.client.force_login(self.owner)
        r = self.client.get('/admin/affiliates/')
        self.assertContains(r, f'/admin/impersonate/start/{self.aff_a.pk}/')


# ─────────────────────────── nesting + owner-only surfaces ──────────────────

class NestingAndPrivilegeTest(ImpersonationBase):
    def test_nested_impersonation_rejected(self):
        self.client.force_login(self.owner)
        self._start(self.aff_a)
        # Now request.user is the affiliate; starting again must be refused.
        r = self.client.post(f'/admin/impersonate/start/{self.aff_b.pk}/')
        self.assertEqual(r.status_code, 403)
        # still impersonating the first target, no second log
        self.assertEqual(self.client.session['impersonate_target_id'], self.aff_a.pk)
        self.assertEqual(ImpersonationLog.objects.count(), 1)

    def test_owner_only_surface_blocked_while_impersonating(self):
        self.client.force_login(self.owner)
        self._start(self.aff_a)
        # Acting as the affiliate: brand CRUD (platform-owner-only) is forbidden.
        r = self.client.get('/admin/brands/')
        self.assertEqual(r.status_code, 403)


# ─────────────────────────── money block / non-money write ──────────────────

class MoneyBlockTest(ImpersonationBase):
    def _impersonate(self, actor, target):
        self.client.force_login(actor)
        self._start(target)

    def test_affiliate_money_paths_blocked(self):
        self._impersonate(self.owner, self.aff_a)
        money_posts = [
            '/partner/payouts/request/',
            '/partner/payouts/methods/add/',
            '/partner/payouts/methods/1/delete/',
            '/partner/payouts/methods/1/set-default/',
            '/partner/payouts/settings/',
        ]
        for url in money_posts:
            r = self.client.post(url, {})
            self.assertEqual(r.status_code, 403, url)
            self.assertIn(b'disabled during impersonation', r.content)

    def test_operator_money_paths_blocked(self):
        self._impersonate(self.owner, self.aff_a)
        for url in ['/admin/payouts/approve/', '/admin/payouts/mark-paid/', '/admin/payouts/dispatch/']:
            r = self.client.post(url, {})
            self.assertEqual(r.status_code, 403, url)
            self.assertIn(b'disabled during impersonation', r.content)

    def test_no_payout_request_created_when_blocked(self):
        from payouts.models import PayoutRequest
        self._impersonate(self.owner, self.aff_a)
        self.client.post('/partner/payouts/request/', {})
        self.assertEqual(PayoutRequest.objects.filter(affiliate=self.aff_a).count(), 0)

    def test_non_money_write_succeeds_while_impersonating(self):
        # Impersonate an advertiser and toggle one of their offers (non-money write).
        from offer.models import ACTIVE_STATUS, Offer, PAUSED_STATUS
        offer = Offer.objects.create(
            title='O', description='d', advertiser=self.adv_a,
            brand=self.brand_a, status=ACTIVE_STATUS,
        )
        self._impersonate(self.admin_a, self.adv_a_user)
        r = self.client.post(f'/advertiser/offers/{offer.id}/status/', {})
        self.assertEqual(r.status_code, 302)
        offer.refresh_from_db()
        self.assertEqual(offer.status, PAUSED_STATUS)  # toggled live, as the target


# ─────────────────────────── audit log ──────────────────────────────────────

class AuditLogTest(ImpersonationBase):
    def test_start_and_stop_recorded_with_ip_and_timestamps(self):
        self.client.force_login(self.admin_a)
        self.client.post(f'/admin/impersonate/start/{self.aff_a.pk}/',
                         HTTP_X_FORWARDED_FOR='9.9.9.9, 10.0.0.1')
        log = ImpersonationLog.objects.get()
        self.assertEqual(log.impersonator, self.admin_a)
        self.assertEqual(log.target, self.aff_a)
        self.assertEqual(log.brand, self.brand_a)
        self.assertEqual(log.impersonator_ip, '9.9.9.9')   # first XFF hop
        self.assertIsNotNone(log.started_at)
        self.assertIsNone(log.ended_at)

        self.client.post('/admin/impersonate/stop/')
        log.refresh_from_db()
        self.assertIsNotNone(log.ended_at)

    def test_owner_sees_all_brand_admin_sees_own(self):
        # one log in brand A, one in brand B
        self.client.force_login(self.admin_a)
        self.client.post(f'/admin/impersonate/start/{self.aff_a.pk}/')
        self.client.post('/admin/impersonate/stop/')
        self.client.force_login(self.admin_b)
        self.client.post(f'/admin/impersonate/start/{self.aff_b.pk}/')
        self.client.post('/admin/impersonate/stop/')

        self.client.force_login(self.owner)
        r = self.client.get('/admin/impersonate/log/')
        self.assertEqual({log.brand_id for log in r.context['logs']},
                         {self.brand_a.id, self.brand_b.id})

        self.client.force_login(self.admin_a)
        r = self.client.get('/admin/impersonate/log/')
        brands_seen = {log.brand_id for log in r.context['logs']}
        self.assertEqual(brands_seen, {self.brand_a.id})

    def test_manager_cannot_view_audit_log(self):
        self.client.force_login(self.mgr_a)
        self.assertEqual(self.client.get('/admin/impersonate/log/').status_code, 403)


# ─────────────────────────── per-request re-validation ──────────────────────

class RevalidationTest(ImpersonationBase):
    def test_target_archived_midsession_ends_impersonation(self):
        self.client.force_login(self.admin_a)
        self._start(self.aff_a)
        self.assertTrue(self._banner_present())
        # Archive the target mid-session.
        p = self.aff_a.profile
        p.is_archived = True
        p.save(update_fields=['is_archived'])
        # Next request: impersonation is revoked, session cleared, log closed.
        self.assertFalse(self._banner_present())
        self.assertNotIn('impersonate_target_id', self.client.session)
        self.assertIsNotNone(ImpersonationLog.objects.get().ended_at)

    def test_target_reassigned_to_other_brand_ends_impersonation(self):
        self.client.force_login(self.admin_a)
        self._start(self.aff_a)
        self.assertTrue(self._banner_present())
        # Reassign target to brand B (out of admin_a's scope).
        p = self.aff_a.profile
        p.brand = self.brand_b
        p.save(update_fields=['brand'])
        self.assertFalse(self._banner_present())
        self.assertNotIn('impersonate_target_id', self.client.session)

    def test_target_deactivated_midsession_ends_impersonation(self):
        self.client.force_login(self.owner)
        self._start(self.aff_a)
        self.assertTrue(self._banner_present())
        self.aff_a.is_active = False
        self.aff_a.save(update_fields=['is_active'])
        self.assertFalse(self._banner_present())
        self.assertNotIn('impersonate_target_id', self.client.session)
