from decimal import Decimal

from django.test import TestCase, override_settings

from offer.models import Advertiser, Offer
from tracker.models import APPROVED_STATUS, REJECTED_STATUS, Click, Conversion
from user_profile.models import Profile, User


# ── fixtures ────────────────────────────────────────────────────────────────

def make_advertiser_user(username):
    """Create a User with ADVERTISER role and a linked Advertiser record."""
    user = User.objects.create_user(username=username, password='pass')
    user.profile.role = Profile.Role.ADVERTISER
    user.profile.save()
    advertiser = Advertiser.objects.create(
        user=user,
        company=f'{username} Co',
        email=f'{username}@example.com',
    )
    return user, advertiser


def make_offer(advertiser, title='Test Offer'):
    return Offer.objects.create(
        title=title,
        advertiser=advertiser,
        tracking_link='http://example.com/track',
        preview_link='http://example.com/preview',
    )


def make_click(offer, n=1):
    for _ in range(n):
        Click.objects.create(
            offer=offer,
            ip='1.2.3.4',
            revenue=Decimal('5.00'),
            payout=Decimal('3.00'),
        )


def make_conversion(offer, status=APPROVED_STATUS, payout=Decimal('10.00'), n=1):
    for _ in range(n):
        Conversion.objects.create(
            offer=offer,
            status=status,
            payout=payout,
            revenue=payout,
        )


# ── tests ────────────────────────────────────────────────────────────────────

@override_settings(CACHES={'default': {'BACKEND': 'django.core.cache.backends.dummy.DummyCache'}})
class DashboardDataIsolationTestCase(TestCase):
    """Each advertiser sees exactly their own data — no cross-contamination."""

    def setUp(self):
        self.user1, self.adv1 = make_advertiser_user('alpha')
        self.user2, self.adv2 = make_advertiser_user('beta')

        self.offer1 = make_offer(self.adv1, 'Offer Alpha')
        self.offer2 = make_offer(self.adv2, 'Offer Beta')

        # adv1: 10 clicks, 3 approved conversions ($10 each), 1 rejected ($5)
        make_click(self.offer1, n=10)
        make_conversion(self.offer1, status=APPROVED_STATUS, payout=Decimal('10.00'), n=3)
        make_conversion(self.offer1, status=REJECTED_STATUS, payout=Decimal('5.00'), n=1)

        # adv2: 5 clicks, 1 approved conversion ($50)
        make_click(self.offer2, n=5)
        make_conversion(self.offer2, status=APPROVED_STATUS, payout=Decimal('50.00'), n=1)

    # ── adv1 sees their own numbers ──────────────────────────────────────────

    def test_adv1_today_clicks(self):
        self.client.force_login(self.user1)
        r = self.client.get('/advertiser/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context['today']['clicks'], 10)

    def test_adv1_today_conversions(self):
        self.client.force_login(self.user1)
        r = self.client.get('/advertiser/')
        # 3 approved + 1 rejected = 4 total conversion events
        self.assertEqual(r.context['today']['conversions'], 4)

    def test_adv1_today_payout_only_approved(self):
        self.client.force_login(self.user1)
        r = self.client.get('/advertiser/')
        # Only 3 approved × $10 — rejected conversion must be excluded
        self.assertEqual(r.context['today']['payout'], Decimal('30.00'))

    def test_adv1_conversion_rate(self):
        self.client.force_login(self.user1)
        r = self.client.get('/advertiser/')
        # 4 conversions / 10 clicks = 40.0%
        self.assertEqual(r.context['today']['cr'], 40.0)

    def test_adv1_top_offers_contains_own_offer(self):
        self.client.force_login(self.user1)
        r = self.client.get('/advertiser/')
        titles = [o['offer__title'] for o in r.context['top_offers']]
        self.assertIn('Offer Alpha', titles)

    # ── adv1 cannot see adv2's data ──────────────────────────────────────────

    def test_adv1_cannot_see_adv2_clicks(self):
        self.client.force_login(self.user1)
        r = self.client.get('/advertiser/')
        # adv1 has 10 clicks; adv2 has 5 — total would be 15 if leaking
        self.assertEqual(r.context['today']['clicks'], 10)

    def test_adv1_top_offers_excludes_adv2_offer(self):
        self.client.force_login(self.user1)
        r = self.client.get('/advertiser/')
        titles = [o['offer__title'] for o in r.context['top_offers']]
        self.assertNotIn('Offer Beta', titles)

    def test_adv1_payout_excludes_adv2_conversions(self):
        self.client.force_login(self.user1)
        r = self.client.get('/advertiser/')
        # Would be $80 if adv2's $50 leaked in
        self.assertEqual(r.context['today']['payout'], Decimal('30.00'))

    # ── adv2 sees their own numbers ──────────────────────────────────────────

    def test_adv2_today_clicks(self):
        self.client.force_login(self.user2)
        r = self.client.get('/advertiser/')
        self.assertEqual(r.context['today']['clicks'], 5)

    def test_adv2_today_payout(self):
        self.client.force_login(self.user2)
        r = self.client.get('/advertiser/')
        self.assertEqual(r.context['today']['payout'], Decimal('50.00'))

    def test_adv2_top_offers_excludes_adv1_offer(self):
        self.client.force_login(self.user2)
        r = self.client.get('/advertiser/')
        titles = [o['offer__title'] for o in r.context['top_offers']]
        self.assertNotIn('Offer Alpha', titles)

    # ── period data: last_7 and last_30 present ──────────────────────────────

    def test_all_period_keys_present(self):
        self.client.force_login(self.user1)
        r = self.client.get('/advertiser/')
        for key in ('today', 'last_7', 'last_30', 'top_offers'):
            self.assertIn(key, r.context)

    def test_last_7_matches_today_for_fresh_data(self):
        """Data created now must appear in both today and last_7 windows."""
        self.client.force_login(self.user1)
        r = self.client.get('/advertiser/')
        self.assertEqual(r.context['last_7']['clicks'], r.context['today']['clicks'])

    # ── no_account fallback ──────────────────────────────────────────────────

    def test_advertiser_role_without_record_shows_no_account(self):
        user = User.objects.create_user(username='orphan', password='pass')
        user.profile.role = Profile.Role.ADVERTISER
        user.profile.save()
        # No Advertiser record linked to this user
        self.client.force_login(user)
        r = self.client.get('/advertiser/')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.context.get('no_account'))

    # ── zero-clicks edge case (no division by zero) ──────────────────────────

    def test_zero_clicks_gives_zero_cr(self):
        _, adv = make_advertiser_user('empty')
        make_offer(adv, 'Empty Offer')  # offer exists but no clicks
        user = adv.user
        self.client.force_login(user)
        r = self.client.get('/advertiser/')
        self.assertEqual(r.context['today']['cr'], 0.0)
        self.assertEqual(r.context['today']['clicks'], 0)


@override_settings(CACHES={'default': {'BACKEND': 'django.core.cache.backends.dummy.DummyCache'}})
class DashboardTemplateTestCase(TestCase):
    """Verify the rendered HTML reflects the data."""

    def setUp(self):
        self.user, self.adv = make_advertiser_user('tmpluser')
        self.offer = make_offer(self.adv, 'Grand Offer')
        make_click(self.offer, n=7)
        make_conversion(self.offer, payout=Decimal('25.00'), n=2)
        self.client.force_login(self.user)

    def test_period_labels_rendered(self):
        r = self.client.get('/advertiser/')
        self.assertContains(r, 'Today')
        self.assertContains(r, 'Last 7 days')
        self.assertContains(r, 'Last 30 days')

    def test_offer_title_in_top_offers_table(self):
        r = self.client.get('/advertiser/')
        self.assertContains(r, 'Grand Offer')

    def test_payout_formatted_with_two_decimals(self):
        r = self.client.get('/advertiser/')
        self.assertContains(r, '50.00')  # 2 × $25.00
