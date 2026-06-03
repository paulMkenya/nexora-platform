"""Advertiser offer create / edit / status-toggle UI.

An advertiser may only create and manage their OWN offers; new offers are
auto-stamped with the advertiser and request.brand, and one advertiser can never
reach another's offer.
"""
from decimal import Decimal

from django.test import TestCase, override_settings

from brands.models import Brand
from offer.models import (
    ACTIVE_STATUS, ALLOW_LIST, BLOCK_LIST, CPL, PAUSED_STATUS,
    Category, Currency, Offer, TrafficSource,
)

from .factories import make_advertiser_user, make_offer


@override_settings(CACHES={'default': {'BACKEND': 'django.core.cache.backends.dummy.DummyCache'}})
class OfferCrudTestCase(TestCase):
    def setUp(self):
        self.user1, self.adv1 = make_advertiser_user('crud1')
        self.user2, self.adv2 = make_advertiser_user('crud2')

    def test_create_offer_is_scoped_to_advertiser_and_brand(self):
        self.client.force_login(self.user1)
        resp = self.client.post('/advertiser/offers/new/', {
            'title': 'Brand New Offer',
            'tracking_link': 'https://example.com/track',
            'status': ACTIVE_STATUS,
            'description': 'hi',
        })
        self.assertEqual(resp.status_code, 302)

        offer = Offer.objects.get(title='Brand New Offer')
        self.assertEqual(offer.advertiser, self.adv1)
        # Auto-stamped with the request brand (the seeded default brand).
        self.assertEqual(offer.brand, Brand.get_default())

    def test_created_offer_appears_in_own_list(self):
        self.client.force_login(self.user1)
        self.client.post('/advertiser/offers/new/', {
            'title': 'Listed Offer',
            'tracking_link': 'https://example.com/track',
            'status': ACTIVE_STATUS,
        })
        r = self.client.get('/advertiser/offers/')
        titles = [o.title for o in r.context['offers']]
        self.assertIn('Listed Offer', titles)

    def test_create_with_initial_payout(self):
        Currency.objects.get_or_create(code='USD', defaults={'name': 'US Dollar'})
        self.client.force_login(self.user1)
        self.client.post('/advertiser/offers/new/', {
            'title': 'Paid Offer',
            'tracking_link': 'https://example.com/track',
            'status': ACTIVE_STATUS,
            'payout_amount': '12.50',
            'currency': 'USD',
        })
        offer = Offer.objects.get(title='Paid Offer')
        payout = offer.payouts.get()
        self.assertEqual(payout.payout, Decimal('12.50'))
        self.assertEqual(payout.currency.code, 'USD')

    def test_missing_title_is_rejected(self):
        self.client.force_login(self.user1)
        resp = self.client.post('/advertiser/offers/new/', {
            'tracking_link': 'https://example.com/track',
        })
        self.assertEqual(resp.status_code, 200)  # re-render, not redirect
        self.assertFalse(Offer.objects.filter(tracking_link='https://example.com/track').exists())

    def test_cannot_edit_another_advertisers_offer(self):
        other = make_offer(self.adv2, 'Foreign Offer', status=ACTIVE_STATUS)
        self.client.force_login(self.user1)

        # GET is blocked
        self.assertEqual(self.client.get(f'/advertiser/offers/{other.pk}/edit/').status_code, 404)
        # POST is blocked and leaves it unchanged
        resp = self.client.post(f'/advertiser/offers/{other.pk}/edit/', {
            'title': 'Hijacked', 'tracking_link': 'https://evil.test',
        })
        self.assertEqual(resp.status_code, 404)
        other.refresh_from_db()
        self.assertEqual(other.title, 'Foreign Offer')

    def test_edit_own_offer(self):
        offer = make_offer(self.adv1, 'Editable', status=ACTIVE_STATUS)
        # make_offer does not set a brand; align it with the request brand so the
        # brand-scoped edit lookup can find it.
        offer.brand = Brand.get_default()
        offer.save(update_fields=['brand'])

        self.client.force_login(self.user1)
        resp = self.client.post(f'/advertiser/offers/{offer.pk}/edit/', {
            'title': 'Edited Title',
            'tracking_link': 'https://example.com/track',
            'status': ACTIVE_STATUS,
        })
        self.assertEqual(resp.status_code, 302)
        offer.refresh_from_db()
        self.assertEqual(offer.title, 'Edited Title')

    def test_pause_and_activate_toggle(self):
        offer = make_offer(self.adv1, 'Toggle Me', status=ACTIVE_STATUS)
        offer.brand = Brand.get_default()
        offer.save(update_fields=['brand'])

        self.client.force_login(self.user1)
        self.client.post(f'/advertiser/offers/{offer.pk}/status/', {'status': 'Paused'})
        offer.refresh_from_db()
        self.assertEqual(offer.status, PAUSED_STATUS)

        self.client.post(f'/advertiser/offers/{offer.pk}/status/', {'status': 'Active'})
        offer.refresh_from_db()
        self.assertEqual(offer.status, ACTIVE_STATUS)

    def test_cannot_toggle_another_advertisers_offer(self):
        other = make_offer(self.adv2, 'Not Yours', status=ACTIVE_STATUS)
        self.client.force_login(self.user1)
        resp = self.client.post(f'/advertiser/offers/{other.pk}/status/', {'status': 'Paused'})
        self.assertEqual(resp.status_code, 404)
        other.refresh_from_db()
        self.assertEqual(other.status, ACTIVE_STATUS)

    def test_create_offer_with_revenue_model_and_traffic_sources(self):
        seo = TrafficSource.objects.create(name='SEO')
        push = TrafficSource.objects.create(name='Push')
        cat = Category.objects.create(name='Finance')
        self.client.force_login(self.user1)
        self.client.post('/advertiser/offers/new/', {
            'title': 'Rich Offer',
            'tracking_link': 'https://example.com/track',
            'status': ACTIVE_STATUS,
            'revenue_model': CPL,
            'country_mode': BLOCK_LIST,
            'icon': 'https://cdn.example.com/creative.png',
            'categories': [str(cat.id)],
            'traffic_sources': [str(seo.id), str(push.id)],
        })
        offer = Offer.objects.get(title='Rich Offer')
        self.assertEqual(offer.revenue_model, CPL)
        self.assertEqual(offer.country_mode, BLOCK_LIST)
        self.assertEqual(offer.icon, 'https://cdn.example.com/creative.png')
        self.assertEqual(set(offer.categories.all()), {cat})
        accepted = set(
            offer.offertrafficsource_set.filter(allowed=True)
            .values_list('traffic_source__name', flat=True))
        self.assertEqual(accepted, {'SEO', 'Push'})

    def test_edit_updates_revenue_model_and_traffic_sources(self):
        offer = make_offer(self.adv1, 'Editable', status=ACTIVE_STATUS)
        offer.brand = Brand.get_default()
        offer.save(update_fields=['brand'])
        seo = TrafficSource.objects.create(name='SEO')

        self.client.force_login(self.user1)
        self.client.post(f'/advertiser/offers/{offer.pk}/edit/', {
            'title': 'Editable',
            'tracking_link': 'https://example.com/track',
            'status': ACTIVE_STATUS,
            'revenue_model': CPL,
            'country_mode': ALLOW_LIST,
            'traffic_sources': [str(seo.id)],
        })
        offer.refresh_from_db()
        self.assertEqual(offer.revenue_model, CPL)
        self.assertEqual(offer.country_mode, ALLOW_LIST)
        self.assertEqual(
            list(offer.offertrafficsource_set.values_list('traffic_source_id', flat=True)),
            [seo.id])
