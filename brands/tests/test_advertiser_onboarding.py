"""Advertiser self-registration, gating, approval, and isolation.

Mirrors the affiliate onboarding model. Two-brand fixture throughout.

Roles:
  * PLATFORM OWNER  = superuser — every advertiser across every brand.
  * BRAND ADMIN     = NETWORK_ADMIN + Profile.brand — only their own brand's
    advertisers; approve/reject/suspend.
  * AFFILIATE MGR   = AFFILIATE_MANAGER — blocked from /admin/advertisers/.
  * ADVERTISER      = self-registers PENDING; gated until APPROVED + verified.

The critical properties under test: brand-scoped registration, object-level
isolation (cross-brand advertiser is a 404 by direct ID), gating of offer
creation, and that a pending advertiser's offers are hidden from affiliates
until approval.
"""
from django.contrib.auth import get_user_model
from django.core import signing
from django.test import TestCase, override_settings

from brands.models import Brand
from offer.models import ACTIVE_STATUS, Advertiser, Offer
from user_profile.models import Profile

User = get_user_model()


def _brand(slug):
    return Brand.objects.create(
        slug=slug, name=f'Brand {slug.upper()}',
        primary_domain=f'{slug}.test', tracking_domain=f't.{slug}.test',
        is_default=(slug == 'a'),
    )


def _user(username, role, brand=None, *, is_staff=False, is_superuser=False):
    u = User.objects.create_user(username, password='pass',
                                 is_staff=is_staff, is_superuser=is_superuser)
    p = u.profile
    p.role = role
    p.brand = brand
    p.save()
    return u


def _advertiser(company, brand, *, status=Advertiser.AdvertiserStatus.APPROVED,
                email_verified=True):
    user = _user(f'adv_{company}', Profile.Role.ADVERTISER, brand)
    adv = Advertiser.objects.create(
        user=user, company=company, email=f'{company}@example.com', brand=brand,
        advertiser_status=status, email_verified=email_verified)
    return user, adv


def _approved_affiliate(username, brand):
    u = _user(username, Profile.Role.AFFILIATE, brand)
    p = u.profile
    p.affiliate_status = Profile.AffiliateStatus.APPROVED
    p.email_verified = True
    p.save()
    return u


@override_settings(CACHES={'default': {'BACKEND': 'django.core.cache.backends.dummy.DummyCache'}})
class OnboardingBase(TestCase):
    def setUp(self):
        self.brand_a = _brand('a')      # default brand, host a.test
        self.brand_b = _brand('b')      # host b.test

        self.owner = User.objects.create_superuser('owner', 'owner@test.com', 'pass')
        self.owner.profile.role = Profile.Role.NETWORK_ADMIN
        self.owner.profile.save(update_fields=['role'])

        self.admin_a = _user('admin_a', Profile.Role.NETWORK_ADMIN, self.brand_a, is_staff=True)
        self.admin_b = _user('admin_b', Profile.Role.NETWORK_ADMIN, self.brand_b, is_staff=True)
        self.mgr_a = _user('mgr_a', Profile.Role.AFFILIATE_MANAGER, self.brand_a)


# ── FIX 1 — self-registration ────────────────────────────────────────────────

class RegistrationTest(OnboardingBase):
    # NOTE: country is intentionally omitted — the country dropdown is sourced
    # from countries_plus, which is not seeded in a fresh test DB. country is
    # optional, so registration succeeds without it; stamping is covered in prod.
    def test_self_register_creates_pending_unverified_advertiser_scoped_to_brand(self):
        resp = self.client.post('/advertiser/register/', {
            'company': 'NewCo',
            'contact_name': 'Jane Doe',
            'email': 'jane@newco.com',
            'password1': 'sup3rsecret!pw',
            'password2': 'sup3rsecret!pw',
            'website': 'https://newco.com',
            'vertical': 'finance',
        }, HTTP_HOST='b.test')
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, '/advertiser/')

        user = User.objects.get(email='jane@newco.com')
        self.assertEqual(user.profile.role, Profile.Role.ADVERTISER)
        self.assertEqual(user.profile.brand, self.brand_b)   # stamped from host

        adv = user.advertiser_profile
        self.assertEqual(adv.brand, self.brand_b)
        self.assertEqual(adv.advertiser_status, Advertiser.AdvertiserStatus.PENDING)
        self.assertFalse(adv.email_verified)
        self.assertEqual(adv.company, 'NewCo')

        # Auto-logged-in.
        self.assertIn('_auth_user_id', self.client.session)

    def test_duplicate_email_rejected(self):
        # Register once through the endpoint so the User.email is set, then
        # attempt a second registration with the same address.
        first = {
            'company': 'Existing', 'contact_name': 'Ex Ist',
            'email': 'dupe@existing.com',
            'password1': 'sup3rsecret!pw', 'password2': 'sup3rsecret!pw',
        }
        self.assertEqual(self.client.post('/advertiser/register/', first, HTTP_HOST='a.test').status_code, 302)
        self.client.logout()

        resp = self.client.post('/advertiser/register/', {
            'company': 'Dupe', 'contact_name': 'Dup E',
            'email': 'Dupe@Existing.com',   # same address, different case
            'password1': 'sup3rsecret!pw', 'password2': 'sup3rsecret!pw',
        }, HTTP_HOST='a.test')
        self.assertEqual(resp.status_code, 200)   # re-render with error
        self.assertContains(resp, 'already exists')
        self.assertEqual(Advertiser.objects.filter(company='Dupe').count(), 0)

    def test_login_page_has_register_link(self):
        resp = self.client.get('/advertiser/login/', HTTP_HOST='a.test')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, '/advertiser/register/')


# ── Email verification ───────────────────────────────────────────────────────

class VerificationTest(OnboardingBase):
    def test_valid_token_flips_email_verified(self):
        user, adv = _advertiser('Verify', self.brand_a,
                                status=Advertiser.AdvertiserStatus.PENDING,
                                email_verified=False)
        token = signing.dumps({'uid': user.pk}, salt='advertiser-email-verify')
        resp = self.client.get(f'/advertiser/verify-email/{token}/', HTTP_HOST='a.test')
        self.assertEqual(resp.status_code, 200)
        adv.refresh_from_db()
        self.assertTrue(adv.email_verified)

    def test_invalid_token_does_not_verify(self):
        user, adv = _advertiser('NoVerify', self.brand_a,
                                status=Advertiser.AdvertiserStatus.PENDING,
                                email_verified=False)
        resp = self.client.get('/advertiser/verify-email/garbage-token/', HTTP_HOST='a.test')
        self.assertEqual(resp.status_code, 200)
        adv.refresh_from_db()
        self.assertFalse(adv.email_verified)


# ── FIX 2 — gating ───────────────────────────────────────────────────────────

class GatingTest(OnboardingBase):
    def test_pending_advertiser_reaches_dashboard_with_banner(self):
        user, _ = _advertiser('Pend', self.brand_a,
                              status=Advertiser.AdvertiserStatus.PENDING,
                              email_verified=False)
        self.client.force_login(user)
        resp = self.client.get('/advertiser/', HTTP_HOST='a.test')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'pending approval')

    def test_pending_advertiser_blocked_from_creating_offers(self):
        user, _ = _advertiser('Pend2', self.brand_a,
                              status=Advertiser.AdvertiserStatus.PENDING,
                              email_verified=False)
        self.client.force_login(user)
        resp = self.client.post('/advertiser/offers/new/', {
            'title': 'Should Fail',
            'tracking_link': 'https://example.com/track',
            'status': ACTIVE_STATUS,
        }, HTTP_HOST='a.test')
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(Offer.objects.filter(title='Should Fail').count(), 0)

    def test_verified_but_unapproved_still_blocked(self):
        user, _ = _advertiser('VerOnly', self.brand_a,
                              status=Advertiser.AdvertiserStatus.PENDING,
                              email_verified=True)
        self.client.force_login(user)
        resp = self.client.get('/advertiser/offers/new/', HTTP_HOST='a.test')
        self.assertEqual(resp.status_code, 403)

    def test_pending_advertiser_offers_hidden_from_affiliates(self):
        _, adv = _advertiser('Hidden', self.brand_a,
                            status=Advertiser.AdvertiserStatus.PENDING,
                            email_verified=False)
        Offer.objects.create(title='Hidden Offer', advertiser=adv, brand=self.brand_a,
                             status=ACTIVE_STATUS, tracking_link='https://example.com/t')
        aff = _approved_affiliate('aff_a', self.brand_a)
        self.client.force_login(aff)
        resp = self.client.get('/partner/offers/', HTTP_HOST='a.test')
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'Hidden Offer')

    def test_approved_advertiser_offers_visible_to_affiliates(self):
        _, adv = _advertiser('Shown', self.brand_a)   # approved + verified
        Offer.objects.create(title='Shown Offer', advertiser=adv, brand=self.brand_a,
                             status=ACTIVE_STATUS, tracking_link='https://example.com/t')
        aff = _approved_affiliate('aff_a2', self.brand_a)
        self.client.force_login(aff)
        resp = self.client.get('/partner/offers/', HTTP_HOST='a.test')
        self.assertContains(resp, 'Shown Offer')

    def test_suspending_advertiser_hides_their_offers(self):
        _, adv = _advertiser('Susp', self.brand_a)
        Offer.objects.create(title='Susp Offer', advertiser=adv, brand=self.brand_a,
                             status=ACTIVE_STATUS, tracking_link='https://example.com/t')
        aff = _approved_affiliate('aff_a3', self.brand_a)
        self.client.force_login(aff)
        # Visible while approved.
        self.assertContains(self.client.get('/partner/offers/', HTTP_HOST='a.test'), 'Susp Offer')
        # Hidden once suspended.
        adv.advertiser_status = Advertiser.AdvertiserStatus.SUSPENDED
        adv.save(update_fields=['advertiser_status'])
        self.assertNotContains(self.client.get('/partner/offers/', HTTP_HOST='a.test'), 'Susp Offer')


class ApprovedAdvertiserCanCreateTest(OnboardingBase):
    def test_approved_verified_advertiser_creates_offer_that_appears_to_affiliates(self):
        adv_user, adv = _advertiser('Active', self.brand_a)   # approved + verified
        self.client.force_login(adv_user)
        resp = self.client.post('/advertiser/offers/new/', {
            'title': 'Live Self Offer',
            'tracking_link': 'https://example.com/track',
            'status': ACTIVE_STATUS,
        }, HTTP_HOST='a.test')
        self.assertEqual(resp.status_code, 302)
        offer = Offer.objects.get(title='Live Self Offer')
        self.assertEqual(offer.advertiser, adv)

        aff = _approved_affiliate('aff_live', self.brand_a)
        self.client.force_login(aff)
        resp = self.client.get('/partner/offers/', HTTP_HOST='a.test')
        self.assertContains(resp, 'Live Self Offer')


# ── FIX 3 — brand-admin approval tool ────────────────────────────────────────

class ApprovalToolTest(OnboardingBase):
    def test_brand_admin_approves_own_brand_advertiser(self):
        _, adv = _advertiser('PendApprove', self.brand_a,
                            status=Advertiser.AdvertiserStatus.PENDING,
                            email_verified=True)
        self.client.force_login(self.admin_a)
        resp = self.client.post(f'/admin/advertisers/{adv.pk}/approve/', HTTP_HOST='a.test')
        self.assertEqual(resp.status_code, 302)
        adv.refresh_from_db()
        self.assertEqual(adv.advertiser_status, Advertiser.AdvertiserStatus.APPROVED)

    def test_brand_admin_list_shows_only_own_brand(self):
        _advertiser('OnlyA', self.brand_a, status=Advertiser.AdvertiserStatus.PENDING)
        _advertiser('OnlyB', self.brand_b, status=Advertiser.AdvertiserStatus.PENDING)
        self.client.force_login(self.admin_a)
        resp = self.client.get('/admin/advertisers/', HTTP_HOST='a.test')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'OnlyA')
        self.assertNotContains(resp, 'OnlyB')

    def test_brand_admin_cannot_approve_other_brand_advertiser_by_id(self):
        _, adv_b = _advertiser('ForeignB', self.brand_b,
                              status=Advertiser.AdvertiserStatus.PENDING)
        self.client.force_login(self.admin_a)
        resp = self.client.post(f'/admin/advertisers/{adv_b.pk}/approve/', HTTP_HOST='a.test')
        self.assertEqual(resp.status_code, 404)
        adv_b.refresh_from_db()
        self.assertEqual(adv_b.advertiser_status, Advertiser.AdvertiserStatus.PENDING)

    def test_brand_admin_cannot_see_other_brand_advertiser_detail_route(self):
        # There is no detail page; the list is the surface — confirm the foreign
        # advertiser never appears and its status actions 404.
        _, adv_b = _advertiser('ForeignB2', self.brand_b,
                              status=Advertiser.AdvertiserStatus.PENDING)
        self.client.force_login(self.admin_a)
        for action in ('approve', 'reject', 'suspend'):
            resp = self.client.post(f'/admin/advertisers/{adv_b.pk}/{action}/', HTTP_HOST='a.test')
            self.assertEqual(resp.status_code, 404)

    def test_status_filter(self):
        _advertiser('FiltPend', self.brand_a, status=Advertiser.AdvertiserStatus.PENDING)
        _advertiser('FiltAppr', self.brand_a)   # approved
        self.client.force_login(self.admin_a)
        resp = self.client.get('/admin/advertisers/?status=PENDING', HTTP_HOST='a.test')
        self.assertContains(resp, 'FiltPend')
        self.assertNotContains(resp, 'FiltAppr')

    def test_superuser_sees_all_brands(self):
        _advertiser('SuOnlyA', self.brand_a)
        _advertiser('SuOnlyB', self.brand_b)
        self.client.force_login(self.owner)
        resp = self.client.get('/admin/advertisers/', HTTP_HOST='a.test')
        self.assertContains(resp, 'SuOnlyA')
        self.assertContains(resp, 'SuOnlyB')

    def test_affiliate_manager_blocked(self):
        self.client.force_login(self.mgr_a)
        self.assertEqual(self.client.get('/admin/advertisers/', HTTP_HOST='a.test').status_code, 403)

    def test_nav_link_visible_to_brand_admin(self):
        self.client.force_login(self.admin_a)
        resp = self.client.get('/admin/advertisers/', HTTP_HOST='a.test')
        self.assertContains(resp, '/admin/advertisers/')

    def test_unauthenticated_redirected(self):
        resp = self.client.get('/admin/advertisers/', HTTP_HOST='a.test')
        self.assertEqual(resp.status_code, 302)
