"""Brand-admin offer management in the operator console (/admin/offers/).

Roles under test (mirrors brands.permissions / brands.scoping):
  * PLATFORM OWNER  = superuser — every offer across every brand.
  * BRAND ADMIN     = NETWORK_ADMIN + Profile.brand — only their own brand's
    offers; creates on behalf of advertisers in their brand only.
  * AFFILIATE MGR   = AFFILIATE_MANAGER — NO offer management (blocked).
  * ADVERTISER      = self-service at /advertiser/offers/* is unaffected.

The critical property is OBJECT-level scoping: another brand's offer is a 404 by
direct ID, and a cross-brand advertiser can never be stamped onto an offer.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from brands.models import Brand
from offer.models import ACTIVE_STATUS, Advertiser, Offer, PAUSED_STATUS
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


def _advertiser(company, brand):
    """An advertiser with its own ADVERTISER-role user, in ``brand``."""
    user = _user(f'adv_{company}', Profile.Role.ADVERTISER, brand)
    adv = Advertiser.objects.create(
        user=user, company=company, email=f'{company}@example.com', brand=brand)
    return user, adv


def _offer(title, advertiser, brand, status=ACTIVE_STATUS):
    return Offer.objects.create(
        title=title, advertiser=advertiser, brand=brand, status=status,
        tracking_link='https://example.com/track')


@override_settings(CACHES={'default': {'BACKEND': 'django.core.cache.backends.dummy.DummyCache'}})
class OfferAdminBase(TestCase):
    def setUp(self):
        self.brand_a = _brand('a')      # default brand
        self.brand_b = _brand('b')

        self.owner = User.objects.create_superuser('owner', 'owner@test.com', 'pass')
        self.owner.profile.role = Profile.Role.NETWORK_ADMIN
        self.owner.profile.save(update_fields=['role'])

        self.admin_a = _user('admin_a', Profile.Role.NETWORK_ADMIN, self.brand_a, is_staff=True)
        self.admin_b = _user('admin_b', Profile.Role.NETWORK_ADMIN, self.brand_b, is_staff=True)
        self.mgr_a = _user('mgr_a', Profile.Role.AFFILIATE_MANAGER, self.brand_a)

        self.adv_user_a, self.adv_a = _advertiser('AcmeA', self.brand_a)
        self.adv_user_b, self.adv_b = _advertiser('AcmeB', self.brand_b)


class BrandAdminCreateTest(OfferAdminBase):
    def test_brand_admin_creates_offer_for_own_brand_advertiser(self):
        self.client.force_login(self.admin_a)
        resp = self.client.post('/admin/offers/new/', {
            'advertiser': self.adv_a.pk,
            'title': 'BA Offer',
            'tracking_link': 'https://example.com/track',
            'status': ACTIVE_STATUS,
        })
        self.assertEqual(resp.status_code, 302)
        offer = Offer.objects.get(title='BA Offer')
        self.assertEqual(offer.advertiser, self.adv_a)
        self.assertEqual(offer.brand, self.brand_a)

    def test_brand_admin_cannot_create_for_other_brand_advertiser(self):
        """Picking a foreign advertiser is rejected server-side (no offer made)."""
        self.client.force_login(self.admin_a)
        resp = self.client.post('/admin/offers/new/', {
            'advertiser': self.adv_b.pk,
            'title': 'Cross Brand',
            'tracking_link': 'https://example.com/track',
            'status': ACTIVE_STATUS,
        })
        self.assertEqual(resp.status_code, 200)  # re-render with error, no redirect
        self.assertFalse(Offer.objects.filter(title='Cross Brand').exists())

    def test_create_advertiser_dropdown_is_brand_scoped(self):
        self.client.force_login(self.admin_a)
        resp = self.client.get('/admin/offers/new/')
        advertisers = set(resp.context['advertisers'])
        self.assertIn(self.adv_a, advertisers)
        self.assertNotIn(self.adv_b, advertisers)


class BrandAdminScopeTest(OfferAdminBase):
    def test_list_shows_only_own_brand_offers(self):
        own = _offer('Own', self.adv_a, self.brand_a)
        foreign = _offer('Foreign', self.adv_b, self.brand_b)
        self.client.force_login(self.admin_a)
        resp = self.client.get('/admin/offers/')
        self.assertEqual(resp.status_code, 200)
        ids = {o.id for o in resp.context['offers']}
        self.assertIn(own.id, ids)
        self.assertNotIn(foreign.id, ids)

    def test_cannot_edit_other_brand_offer_by_id(self):
        foreign = _offer('Foreign', self.adv_b, self.brand_b)
        self.client.force_login(self.admin_a)
        self.assertEqual(
            self.client.get(f'/admin/offers/{foreign.pk}/edit/').status_code, 404)
        resp = self.client.post(f'/admin/offers/{foreign.pk}/edit/', {
            'advertiser': self.adv_b.pk, 'title': 'Hijacked',
            'tracking_link': 'https://evil.test', 'status': ACTIVE_STATUS,
        })
        self.assertEqual(resp.status_code, 404)
        foreign.refresh_from_db()
        self.assertEqual(foreign.title, 'Foreign')

    def test_cannot_toggle_other_brand_offer_status(self):
        foreign = _offer('Foreign', self.adv_b, self.brand_b, status=ACTIVE_STATUS)
        self.client.force_login(self.admin_a)
        resp = self.client.post(f'/admin/offers/{foreign.pk}/status/', {'status': PAUSED_STATUS})
        self.assertEqual(resp.status_code, 404)
        foreign.refresh_from_db()
        self.assertEqual(foreign.status, ACTIVE_STATUS)

    def test_edit_own_brand_offer(self):
        own = _offer('Editable', self.adv_a, self.brand_a)
        self.client.force_login(self.admin_a)
        resp = self.client.post(f'/admin/offers/{own.pk}/edit/', {
            'advertiser': self.adv_a.pk, 'title': 'Edited',
            'tracking_link': 'https://example.com/track', 'status': ACTIVE_STATUS,
        })
        self.assertEqual(resp.status_code, 302)
        own.refresh_from_db()
        self.assertEqual(own.title, 'Edited')

    def test_pause_activate_toggle_own_offer(self):
        own = _offer('Toggle', self.adv_a, self.brand_a, status=ACTIVE_STATUS)
        self.client.force_login(self.admin_a)
        self.client.post(f'/admin/offers/{own.pk}/status/', {'status': PAUSED_STATUS})
        own.refresh_from_db()
        self.assertEqual(own.status, PAUSED_STATUS)
        self.client.post(f'/admin/offers/{own.pk}/status/', {'status': ACTIVE_STATUS})
        own.refresh_from_db()
        self.assertEqual(own.status, ACTIVE_STATUS)


class AffiliateManagerBlockedTest(OfferAdminBase):
    def test_manager_blocked_from_list(self):
        self.client.force_login(self.mgr_a)
        self.assertEqual(self.client.get('/admin/offers/').status_code, 403)

    def test_manager_blocked_from_create(self):
        self.client.force_login(self.mgr_a)
        resp = self.client.post('/admin/offers/new/', {
            'advertiser': self.adv_a.pk, 'title': 'Nope',
            'tracking_link': 'https://example.com/track', 'status': ACTIVE_STATUS,
        })
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(Offer.objects.filter(title='Nope').exists())

    def test_manager_nav_has_no_offers_link(self):
        self.client.force_login(self.mgr_a)
        resp = self.client.get('/admin/affiliates/')
        self.assertNotContains(resp, '/admin/offers/')


class PlatformOwnerCrossBrandTest(OfferAdminBase):
    def test_owner_sees_all_brand_offers(self):
        a = _offer('A', self.adv_a, self.brand_a)
        b = _offer('B', self.adv_b, self.brand_b)
        self.client.force_login(self.owner)
        resp = self.client.get('/admin/offers/')
        ids = {o.id for o in resp.context['offers']}
        self.assertIn(a.id, ids)
        self.assertIn(b.id, ids)

    def test_owner_creates_for_any_brand_advertiser(self):
        self.client.force_login(self.owner)
        resp = self.client.post('/admin/offers/new/', {
            'advertiser': self.adv_b.pk, 'title': 'Owner Made',
            'tracking_link': 'https://example.com/track', 'status': ACTIVE_STATUS,
        })
        self.assertEqual(resp.status_code, 302)
        offer = Offer.objects.get(title='Owner Made')
        self.assertEqual(offer.advertiser, self.adv_b)
        self.assertEqual(offer.brand, self.brand_b)

    def test_owner_can_edit_any_brand_offer(self):
        b = _offer('B', self.adv_b, self.brand_b)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(f'/admin/offers/{b.pk}/edit/').status_code, 200)


class NavLinkVisibilityTest(OfferAdminBase):
    def test_brand_admin_sees_offers_nav_link(self):
        self.client.force_login(self.admin_a)
        resp = self.client.get('/admin/offers/')
        self.assertContains(resp, 'href="/admin/offers/"')


class AdvertiserSelfServiceIntactTest(OfferAdminBase):
    """The advertiser self-service create at /advertiser/offers/* is unchanged."""

    def test_advertiser_self_service_create_still_works(self):
        self.client.force_login(self.adv_user_a)
        resp = self.client.post('/advertiser/offers/new/', {
            'title': 'Self Service',
            'tracking_link': 'https://example.com/track',
            'status': ACTIVE_STATUS,
        })
        self.assertEqual(resp.status_code, 302)
        offer = Offer.objects.get(title='Self Service')
        self.assertEqual(offer.advertiser, self.adv_a)
        self.assertEqual(offer.brand, self.brand_a)

    def test_advertiser_cannot_reach_operator_offers(self):
        """An advertiser is not a brand admin → blocked from the console."""
        self.client.force_login(self.adv_user_a)
        self.assertEqual(self.client.get('/admin/offers/').status_code, 403)
