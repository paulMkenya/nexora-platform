from decimal import Decimal

from django.test import TestCase, override_settings

from tracker.models import APPROVED_STATUS, REJECTED_STATUS
from user_profile.models import Profile, User

from .factories import make_advertiser_user, make_click, make_conversion, make_offer


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

    def test_adv1_today_clicks(self):
        self.client.force_login(self.user1)
        r = self.client.get('/advertiser/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context['today']['clicks'], 10)

    def test_adv1_today_conversions(self):
        self.client.force_login(self.user1)
        r = self.client.get('/advertiser/')
        self.assertEqual(r.context['today']['conversions'], 4)

    def test_adv1_today_payout_only_approved(self):
        self.client.force_login(self.user1)
        r = self.client.get('/advertiser/')
        self.assertEqual(r.context['today']['payout'], Decimal('30.00'))

    def test_adv1_conversion_rate(self):
        self.client.force_login(self.user1)
        r = self.client.get('/advertiser/')
        self.assertEqual(r.context['today']['cr'], 40.0)

    def test_adv1_top_offers_contains_own_offer(self):
        self.client.force_login(self.user1)
        r = self.client.get('/advertiser/')
        titles = [o['offer__title'] for o in r.context['top_offers']]
        self.assertIn('Offer Alpha', titles)

    def test_adv1_cannot_see_adv2_clicks(self):
        self.client.force_login(self.user1)
        r = self.client.get('/advertiser/')
        self.assertEqual(r.context['today']['clicks'], 10)

    def test_adv1_top_offers_excludes_adv2_offer(self):
        self.client.force_login(self.user1)
        r = self.client.get('/advertiser/')
        titles = [o['offer__title'] for o in r.context['top_offers']]
        self.assertNotIn('Offer Beta', titles)

    def test_adv1_payout_excludes_adv2_conversions(self):
        self.client.force_login(self.user1)
        r = self.client.get('/advertiser/')
        self.assertEqual(r.context['today']['payout'], Decimal('30.00'))

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

    def test_all_period_keys_present(self):
        self.client.force_login(self.user1)
        r = self.client.get('/advertiser/')
        for key in ('today', 'last_7', 'last_30', 'top_offers'):
            self.assertIn(key, r.context)

    def test_last_7_matches_today_for_fresh_data(self):
        self.client.force_login(self.user1)
        r = self.client.get('/advertiser/')
        self.assertEqual(r.context['last_7']['clicks'], r.context['today']['clicks'])

    def test_advertiser_role_without_record_shows_no_account(self):
        user = User.objects.create_user(username='orphan', password='pass')
        user.profile.role = Profile.Role.ADVERTISER
        user.profile.save()
        self.client.force_login(user)
        r = self.client.get('/advertiser/')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.context.get('no_account'))

    def test_zero_clicks_gives_zero_cr(self):
        _, adv = make_advertiser_user('empty')
        make_offer(adv, 'Empty Offer')
        self.client.force_login(adv.user)
        r = self.client.get('/advertiser/')
        self.assertEqual(r.context['today']['cr'], 0.0)
        self.assertEqual(r.context['today']['clicks'], 0)


@override_settings(CACHES={'default': {'BACKEND': 'django.core.cache.backends.dummy.DummyCache'}})
class DashboardTemplateTestCase(TestCase):
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
        self.assertContains(r, '50.00')
