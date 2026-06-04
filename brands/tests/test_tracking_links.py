"""Brand-aware tracking link generation & click attribution.

Covers the white-label isolation requirement: a brand's affiliate/advertiser
must only ever see that brand's own tracking domain, and a click must be
attributed to the offer's brand.
"""
import uuid
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from brands.links import affiliate_click_link, tracking_base_url
from brands.models import Brand
from offer.models import ACTIVE_STATUS, Offer
from tracker.models import Click
from tracker.tasks.click import click as click_task, resolve_click_brand


class _FakeRequest:
    def __init__(self, brand):
        self.brand = brand


class BrandLinkResolutionTest(TestCase):
    def setUp(self):
        # `nexora` (t.cloudtrade.pro) is created by migration 0002 as the default.
        self.nexora = Brand.objects.get(slug='nexora')
        self.ccs = Brand.objects.create(
            slug='ccs', name='CloudTrade Systems',
            primary_domain='cpa.cloudtradesystems.test',
            tracking_domain='t.cloudtradesystems.com',
        )

    def test_ccs_offer_uses_ccs_tracking_domain(self):
        offer = Offer.objects.create(title='CCS Offer', brand=self.ccs, status=ACTIVE_STATUS)
        self.assertEqual(
            affiliate_click_link(offer, 7),
            f'https://t.cloudtradesystems.com/click?offer_id={offer.id}&pid=7',
        )

    def test_nexora_offer_uses_nexora_tracking_domain(self):
        offer = Offer.objects.create(title='Nexora Offer', brand=self.nexora, status=ACTIVE_STATUS)
        self.assertEqual(
            affiliate_click_link(offer, 7),
            f'https://t.cloudtrade.pro/click?offer_id={offer.id}&pid=7',
        )

    def test_unbranded_offer_falls_back_to_request_brand(self):
        offer = Offer.objects.create(title='Legacy', status=ACTIVE_STATUS)  # no brand
        link = affiliate_click_link(offer, 1, request=_FakeRequest(self.ccs))
        self.assertTrue(link.startswith('https://t.cloudtradesystems.com/click?'))

    @override_settings(TRACKER_URL='https://t.example.com')
    def test_unbranded_offer_no_request_falls_back_to_global(self):
        offer = Offer.objects.create(title='Legacy', status=ACTIVE_STATUS)
        self.assertEqual(
            affiliate_click_link(offer, 1),
            f'https://t.example.com/click?offer_id={offer.id}&pid=1',
        )

    def test_offer_brand_beats_request_brand_no_cross_leak(self):
        # CCS offer viewed by a request resolved to the nexora brand must STILL
        # use the CCS domain — never leak nexora's domain onto a CCS link.
        offer = Offer.objects.create(title='CCS', brand=self.ccs, status=ACTIVE_STATUS)
        link = affiliate_click_link(offer, 9, request=_FakeRequest(self.nexora))
        self.assertIn('t.cloudtradesystems.com', link)
        self.assertNotIn('t.cloudtrade.pro', link)

    def test_blank_brand_tracking_domain_falls_through(self):
        blank = Brand.objects.create(
            slug='blank', name='Blank', primary_domain='cpa.blank.test',
            tracking_domain='',  # not yet configured
        )
        offer = Offer.objects.create(title='B', brand=blank, status=ACTIVE_STATUS)
        # No brand domain anywhere → global fallback.
        with override_settings(TRACKER_URL='https://t.example.com'):
            self.assertEqual(tracking_base_url(brand=offer.brand), 'https://t.example.com')


class ClickAttributionTest(TestCase):
    def setUp(self):
        self.nexora = Brand.objects.get(slug='nexora')
        self.ccs = Brand.objects.create(
            slug='ccs', name='CloudTrade Systems',
            primary_domain='cpa.cloudtradesystems.test',
            tracking_domain='t.cloudtradesystems.com',
        )

    def test_offer_brand_is_authoritative(self):
        offer = Offer.objects.create(title='CCS', brand=self.ccs, status=ACTIVE_STATUS)
        self.assertEqual(resolve_click_brand(offer.id, self.ccs.id), self.ccs.id)

    def test_mismatch_attributes_to_offer_brand_and_logs(self):
        # Click arrives on the nexora domain for a CCS offer → attribute to CCS,
        # never silently cross-attribute, and log the mismatch.
        offer = Offer.objects.create(title='CCS', brand=self.ccs, status=ACTIVE_STATUS)
        with self.assertLogs('tracker.tasks.click', level='WARNING') as cm:
            result = resolve_click_brand(offer.id, self.nexora.id)
        self.assertEqual(result, self.ccs.id)
        self.assertIn('mismatch', ''.join(cm.output).lower())

    def test_unbranded_offer_uses_request_brand(self):
        offer = Offer.objects.create(title='Legacy', status=ACTIVE_STATUS)  # no brand
        self.assertEqual(resolve_click_brand(offer.id, self.nexora.id), self.nexora.id)

    @mock.patch('fraud.tasks.score_click_fraud')
    @mock.patch('tracker.tasks.click.detect_country_service', return_value='US')
    def test_click_endpoint_attributes_to_offer_brand_end_to_end(self, _country, _fraud):
        affiliate = User.objects.create_user(username='aff-e2e', password='x')
        offer = Offer.objects.create(title='CCS', brand=self.ccs, status=ACTIVE_STATUS)
        click_id = uuid.uuid4().hex
        data = {
            'click_id': click_id,
            'offer_id': offer.id,
            'pid': affiliate.id,
            # Click physically arrived on the nexora tracking domain...
            'request_brand_id': self.nexora.id,
            'ip': '1.2.3.4', 'ua': 'UA',
            'sub1': '', 'sub2': '', 'sub3': '', 'sub4': '', 'sub5': '',
        }
        click_task(data)
        saved = Click.objects.get(pk=click_id)
        # ...but it is attributed to the OFFER's brand (CCS).
        self.assertEqual(saved.brand_id, self.ccs.id)


class ClickViewBrandTest(TestCase):
    def setUp(self):
        self.ccs = Brand.objects.create(
            slug='ccs', name='CloudTrade Systems',
            primary_domain='cpa.cloudtradesystems.test',
            tracking_domain='t.cloudtradesystems.com',
        )

    @mock.patch('tracker.views.click_task')
    @mock.patch('tracker.dao.TrackerCache.get_offer',
                return_value={'tracking_link': 'http://dest.example'})
    def test_click_on_brand_domain_passes_brand(self, _cache, mock_task):
        # Reaching /click via the CCS tracking domain must resolve request.brand
        # to CCS (BrandMiddleware) and forward it for attribution.
        self.client.get(
            reverse('tracker-click'),
            {'offer_id': 1, 'pid': 5},
            HTTP_HOST='t.cloudtradesystems.com',
            HTTP_USER_AGENT='UA',
        )
        data = mock_task.delay.call_args[0][0]
        self.assertEqual(data['request_brand_id'], self.ccs.id)
