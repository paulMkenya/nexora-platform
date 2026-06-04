from django.test import TestCase
from django.contrib.auth.models import User
from django.urls import reverse
from django.conf import settings

from offer.models import (
    Offer, Category, Payout, Currency, Goal, OfferTrafficSource, TrafficSource,
    ACTIVE_STATUS, PAUSED_STATUS, ALLOW_LIST, CPA, CPL,
)
from affiliate_ui.views.general_views import generate_tracking_link
from brands.models import Brand
from user_profile.models import Profile


def _approve(user):
    user.profile.affiliate_status = Profile.AffiliateStatus.APPROVED
    user.profile.email_verified = True
    user.profile.save()


class OfferListViewTest(TestCase):
    def setUp(self):
        self.username = 'testuser_offers'
        self.password = 'testpass123'
        self.user = User.objects.create_user(username=self.username, password=self.password)
        _approve(self.user)
        self.offers_url = reverse('affiliate_ui:offer_list')
        self.login_url = reverse('affiliate_ui:login')

        self.category1 = Category.objects.create(name='Finance')
        self.category2 = Category.objects.create(name='E-commerce')

        self.currency = Currency.objects.create(code='USD', name='US Dollar', symbol='$')
        self.goal = Goal.objects.create(name='Test Goal')

        self.offer1 = Offer.objects.create(
            title='Credit Card Offer', description='Financial offer', status=ACTIVE_STATUS)
        self.offer1.categories.add(self.category1)
        Payout.objects.create(
            offer=self.offer1, revenue=10, payout=5, currency=self.currency, goal=self.goal)

        self.offer2 = Offer.objects.create(
            title='Online Store Discount', description='Retail offer', status=ACTIVE_STATUS)
        self.offer2.categories.add(self.category2)
        Payout.objects.create(
            offer=self.offer2, revenue=20, payout=10, currency=self.currency, goal=self.goal)

        self.offer3 = Offer.objects.create(
            title='Inactive Offer', description='Should not be visible', status=PAUSED_STATUS)

    def test_offer_list_view_login_required(self):
        response = self.client.get(self.offers_url)
        self.assertRedirects(response, f'{self.login_url}?next={self.offers_url}')

    def test_offer_list_view_authenticated(self):
        self.client.login(username=self.username, password=self.password)
        response = self.client.get(self.offers_url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'affiliate_ui/offers.html')

    def test_offer_list_displays_offers(self):
        self.client.login(username=self.username, password=self.password)
        response = self.client.get(self.offers_url)
        self.assertContains(response, 'Credit Card Offer')
        self.assertContains(response, 'Online Store Discount')
        self.assertNotContains(response, 'Inactive Offer')
        self.assertContains(response, '$5.00')
        self.assertContains(response, '$10.00')

    def test_offer_search(self):
        self.client.login(username=self.username, password=self.password)
        response = self.client.get(self.offers_url, {'search': 'Credit'})
        self.assertContains(response, 'Credit Card Offer')
        self.assertNotContains(response, 'Online Store Discount')

    def test_offer_filter_by_category(self):
        self.client.login(username=self.username, password=self.password)
        response = self.client.get(self.offers_url, {'category': self.category1.id})
        self.assertContains(response, 'Credit Card Offer')
        self.assertNotContains(response, 'Online Store Discount')


class OfferBrowseFilterTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='browse', password='pass')
        _approve(self.user)
        self.client.login(username='browse', password='pass')
        self.url = reverse('affiliate_ui:offer_list')

        self.currency = Currency.objects.create(code='USD', name='US Dollar', symbol='$')
        self.cat = Category.objects.create(name='Finance')
        self.seo = TrafficSource.objects.create(name='SEO')
        self.push = TrafficSource.objects.create(name='Push')

        self.cpa = Offer.objects.create(title='CPA Offer', status=ACTIVE_STATUS, revenue_model=CPA)
        Payout.objects.create(offer=self.cpa, revenue=10, payout=5, currency=self.currency)
        OfferTrafficSource.objects.create(offer=self.cpa, traffic_source=self.seo, allowed=True)

        self.cpl = Offer.objects.create(title='CPL Offer', status=ACTIVE_STATUS, revenue_model=CPL)
        Payout.objects.create(offer=self.cpl, revenue=80, payout=50, currency=self.currency)
        OfferTrafficSource.objects.create(offer=self.cpl, traffic_source=self.push, allowed=True)

    def test_filter_by_revenue_model(self):
        r = self.client.get(self.url, {'revenue_model': CPL})
        self.assertContains(r, 'CPL Offer')
        self.assertNotContains(r, 'CPA Offer')

    def test_filter_by_payout_range(self):
        r = self.client.get(self.url, {'payout_min': '40'})
        self.assertContains(r, 'CPL Offer')
        self.assertNotContains(r, 'CPA Offer')
        r = self.client.get(self.url, {'payout_max': '10'})
        self.assertContains(r, 'CPA Offer')
        self.assertNotContains(r, 'CPL Offer')

    def test_filter_by_traffic_source(self):
        r = self.client.get(self.url, {'traffic_source': self.seo.id})
        self.assertContains(r, 'CPA Offer')
        self.assertNotContains(r, 'CPL Offer')

    def test_filter_by_country_allow_list(self):
        from countries_plus.models import Country
        ke = Country.objects.get_or_create(
            iso='KE', defaults={'name': 'Kenya', 'iso3': 'KEN', 'iso_numeric': 404})[0]
        self.cpl.country_mode = ALLOW_LIST
        self.cpl.save()
        self.cpl.countries.add(ke)
        # CPA stays ALLOW_ALL → always shown; CPL only for KE.
        r = self.client.get(self.url, {'country': 'KE'})
        self.assertContains(r, 'CPL Offer')
        r = self.client.get(self.url, {'country': 'NG'})
        self.assertNotContains(r, 'CPL Offer')
        self.assertContains(r, 'CPA Offer')

    def test_brand_isolation(self):
        other_brand = Brand.objects.create(
            slug='other', name='Other', primary_domain='other.test',
            tracking_domain='t.other.test')
        foreign = Offer.objects.create(
            title='Foreign Brand Offer', status=ACTIVE_STATUS, brand=other_brand)
        r = self.client.get(self.url)
        self.assertNotContains(r, 'Foreign Brand Offer')
        # And the detail page 404s for an offer outside the affiliate's brand.
        self.assertEqual(
            self.client.get(reverse('affiliate_ui:offer_detail', args=[foreign.id])).status_code,
            404)


class OfferDetailViewTest(TestCase):
    def setUp(self):
        self.username = 'testuser_offer_detail'
        self.password = 'testpass123'
        self.user = User.objects.create_user(username=self.username, password=self.password)
        _approve(self.user)
        self.login_url = reverse('affiliate_ui:login')

        self.currency = Currency.objects.create(code='USD', name='US Dollar')
        self.goal = Goal.objects.create(name='Test Goal')

        self.offer = Offer.objects.create(
            title='Detailed Offer',
            description_html='<p>Test Description</p>',
            status=ACTIVE_STATUS
        )
        Payout.objects.create(offer=self.offer, revenue=15, payout=7.5, currency=self.currency, goal=self.goal)
        self.offer_detail_url = reverse('affiliate_ui:offer_detail', args=[self.offer.id])

    def test_offer_detail_view_login_required(self):
        response = self.client.get(self.offer_detail_url)
        self.assertRedirects(response, f'{self.login_url}?next={self.offer_detail_url}')

    def test_offer_detail_view_authenticated(self):
        self.client.login(username=self.username, password=self.password)
        response = self.client.get(self.offer_detail_url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'affiliate_ui/offer_details.html')
        self.assertContains(response, 'Detailed Offer')
        self.assertContains(response, '<p>Test Description</p>')
        self.assertContains(response, '7.5') # Payout

    def test_tracking_link_uses_offer_brand_domain(self):
        # An offer on the CCS brand, viewed on the CCS domain, must show a click
        # link on CCS's own tracking domain — never the platform domain.
        ccs = Brand.objects.create(
            slug='ccs-detail', name='CCS',
            primary_domain='cpa.cloudtradesystems.test',
            tracking_domain='t.cloudtradesystems.com',
        )
        self.offer.brand = ccs
        self.offer.save(update_fields=['brand'])

        self.client.login(username=self.username, password=self.password)
        response = self.client.get(
            self.offer_detail_url, HTTP_HOST='cpa.cloudtradesystems.test'
        )
        expected_link = (
            f"https://t.cloudtradesystems.com/click"
            f"?offer_id={self.offer.id}&amp;pid={self.user.id}"
        )
        self.assertContains(response, expected_link)
        # The platform fallback domain must not leak onto a brand page.
        self.assertNotContains(response, settings.TRACKER_URL)

    def test_generate_tracking_link_function(self):
        # No request and no brand on the offer → falls back to global TRACKER_URL.
        offer = Offer.objects.create(id=4321, title='x', status=ACTIVE_STATUS)
        expected_link = f"{settings.TRACKER_URL}/click?offer_id={offer.id}&pid=100"
        self.assertEqual(generate_tracking_link(offer, 100), expected_link)
