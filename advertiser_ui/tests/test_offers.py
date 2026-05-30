from decimal import Decimal

from django.test import TestCase, override_settings
from django.urls import reverse


from tracker.models import APPROVED_STATUS, REJECTED_STATUS
from user_profile.models import Profile, User

from .factories import (
    make_advertiser_user,
    make_click,
    make_conversion,
    make_offer,
    make_payout,
)


@override_settings(CACHES={'default': {'BACKEND': 'django.core.cache.backends.dummy.DummyCache'}})
class OffersListIsolationTestCase(TestCase):
    """Advertiser can only see their own offers — no cross-advertiser data."""

    def setUp(self):
        self.user1, self.adv1 = make_advertiser_user('ofruser1')
        self.user2, self.adv2 = make_advertiser_user('ofruser2')

        self.offer_a = make_offer(self.adv1, 'Alpha Offer', status='Active')
        self.offer_b = make_offer(self.adv1, 'Beta Offer',  status='Paused')
        self.offer_c = make_offer(self.adv2, 'Gamma Offer', status='Active')

        make_payout(self.offer_a, payout=Decimal('15.00'))
        make_click(self.offer_a, n=8)
        make_conversion(self.offer_a, status=APPROVED_STATUS, payout=Decimal('15.00'), n=3)
        make_conversion(self.offer_a, status=REJECTED_STATUS, payout=Decimal('5.00'), n=2)

        make_click(self.offer_c, n=20)
        make_conversion(self.offer_c, status=APPROVED_STATUS, payout=Decimal('100.00'), n=10)

    # ── isolation ──────────────────────────────────────────────────────────

    def test_adv1_sees_only_own_offers(self):
        self.client.force_login(self.user1)
        r = self.client.get('/advertiser/offers/')
        titles = [o.title for o in r.context['offers']]
        self.assertIn('Alpha Offer', titles)
        self.assertIn('Beta Offer', titles)
        self.assertNotIn('Gamma Offer', titles)

    def test_adv2_sees_only_own_offers(self):
        self.client.force_login(self.user2)
        r = self.client.get('/advertiser/offers/')
        titles = [o.title for o in r.context['offers']]
        self.assertIn('Gamma Offer', titles)
        self.assertNotIn('Alpha Offer', titles)
        self.assertNotIn('Beta Offer', titles)

    # ── per-offer stats correctness ────────────────────────────────────────

    def test_clicks_30d_correct(self):
        self.client.force_login(self.user1)
        r = self.client.get('/advertiser/offers/')
        alpha = next(o for o in r.context['offers'] if o.title == 'Alpha Offer')
        self.assertEqual(alpha.clicks_30d, 8)

    def test_conversions_30d_counts_all_statuses(self):
        self.client.force_login(self.user1)
        r = self.client.get('/advertiser/offers/')
        alpha = next(o for o in r.context['offers'] if o.title == 'Alpha Offer')
        # 3 approved + 2 rejected = 5
        self.assertEqual(alpha.conversions_30d, 5)

    def test_revenue_30d_only_approved(self):
        self.client.force_login(self.user1)
        r = self.client.get('/advertiser/offers/')
        alpha = next(o for o in r.context['offers'] if o.title == 'Alpha Offer')
        # 3 × $15.00 — rejected conversions must NOT contribute
        self.assertEqual(alpha.revenue_30d, Decimal('45.00'))

    def test_adv1_revenue_excludes_adv2_conversions(self):
        self.client.force_login(self.user1)
        r = self.client.get('/advertiser/offers/')
        total_revenue = sum(o.revenue_30d for o in r.context['offers'])
        # adv2 has $1000 revenue — must not bleed in
        self.assertEqual(total_revenue, Decimal('45.00'))

    def test_best_payout_annotated(self):
        self.client.force_login(self.user1)
        r = self.client.get('/advertiser/offers/')
        alpha = next(o for o in r.context['offers'] if o.title == 'Alpha Offer')
        self.assertEqual(alpha.best_payout, Decimal('15.00'))

    def test_offer_with_no_payout_has_none_best_payout(self):
        self.client.force_login(self.user1)
        r = self.client.get('/advertiser/offers/')
        beta = next(o for o in r.context['offers'] if o.title == 'Beta Offer')
        self.assertIsNone(beta.best_payout)

    def test_offer_with_no_activity_has_zero_stats(self):
        self.client.force_login(self.user1)
        r = self.client.get('/advertiser/offers/')
        beta = next(o for o in r.context['offers'] if o.title == 'Beta Offer')
        self.assertEqual(beta.clicks_30d, 0)
        self.assertEqual(beta.conversions_30d, 0)
        self.assertEqual(beta.revenue_30d, Decimal('0.00'))

    # ── status filter ─────────────────────────────────────────────────────

    def test_status_filter_active(self):
        self.client.force_login(self.user1)
        r = self.client.get('/advertiser/offers/?status=Active')
        titles = [o.title for o in r.context['offers']]
        self.assertIn('Alpha Offer', titles)
        self.assertNotIn('Beta Offer', titles)

    def test_status_filter_paused(self):
        self.client.force_login(self.user1)
        r = self.client.get('/advertiser/offers/?status=Paused')
        titles = [o.title for o in r.context['offers']]
        self.assertIn('Beta Offer', titles)
        self.assertNotIn('Alpha Offer', titles)

    def test_status_filter_nonexistent_returns_empty(self):
        self.client.force_login(self.user1)
        r = self.client.get('/advertiser/offers/?status=Stopped')
        self.assertEqual(len(r.context['offers']), 0)

    def test_status_counts_correct(self):
        self.client.force_login(self.user1)
        r = self.client.get('/advertiser/offers/')
        counts = r.context['status_counts']
        self.assertEqual(counts.get('Active', 0), 1)
        self.assertEqual(counts.get('Paused', 0), 1)

    # ── access control ─────────────────────────────────────────────────────

    def test_unauthenticated_redirected(self):
        r = self.client.get('/advertiser/offers/')
        self.assertRedirects(r, '/login/?next=/advertiser/offers/',
                             fetch_redirect_response=False)

    def test_non_advertiser_role_gets_403(self):
        user = User.objects.create_user(username='aff_ofr', password='pass')
        user.profile.role = Profile.Role.AFFILIATE
        user.profile.save()
        self.client.force_login(user)
        self.assertEqual(self.client.get('/advertiser/offers/').status_code, 403)

    def test_url_reverses_correctly(self):
        self.assertEqual(reverse('advertiser_ui:offers'), '/advertiser/offers/')


@override_settings(CACHES={'default': {'BACKEND': 'django.core.cache.backends.dummy.DummyCache'}})
class OffersTemplateTestCase(TestCase):
    def setUp(self):
        self.user, self.adv = make_advertiser_user('tmpl_ofr')
        self.offer = make_offer(self.adv, 'Template Offer', status='Active')
        make_payout(self.offer, payout=Decimal('20.00'))
        make_click(self.offer, n=4)
        make_conversion(self.offer, payout=Decimal('20.00'), n=2)
        self.client.force_login(self.user)

    def test_offer_title_rendered(self):
        r = self.client.get('/advertiser/offers/')
        self.assertContains(r, 'Template Offer')

    def test_active_badge_rendered(self):
        r = self.client.get('/advertiser/offers/')
        self.assertContains(r, 'Active')

    def test_payout_column_rendered(self):
        r = self.client.get('/advertiser/offers/')
        self.assertContains(r, '20.00')

    def test_filter_pills_rendered(self):
        r = self.client.get('/advertiser/offers/')
        self.assertContains(r, '?status=Active')
        self.assertContains(r, '?status=Paused')
        self.assertContains(r, '?status=Stopped')

    def test_empty_state_shown_when_filter_has_no_matches(self):
        r = self.client.get('/advertiser/offers/?status=Stopped')
        self.assertContains(r, 'No')
        self.assertContains(r, 'Clear filter')

    def test_status_filter_context_set(self):
        r = self.client.get('/advertiser/offers/?status=Active')
        self.assertEqual(r.context['status_filter'], 'Active')
