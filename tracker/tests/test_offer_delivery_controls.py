"""Offer delivery controls applied when a conversion is recorded: carrier
(ASN) allow list, daily conversion cap, and advertiser txid dedupe. Also the
GeoLite2 fallback and ASN parsing behind the click's network fields."""
from unittest import mock

from countries_plus.models import Country
from django.contrib.auth import get_user_model
from django.test import TestCase

from ext.ipapi import Err, Response, parse_asn
from offer.models import Currency, Offer, Payout
from tracker.models import Click, Conversion
from tracker.tasks.click import lookup_ip
from tracker.tasks.conversion import conversion


@mock.patch('billing.tasks.debit.debit_conversion')
@mock.patch('fraud.tasks.score_conversion_fraud')
@mock.patch('tracker.signals.send_postback')
class DeliveryControlsTests(TestCase):

    def setUp(self):
        self.aff = get_user_model().objects.create_user(username='aff', password='x')
        self.offer = Offer.objects.create(title='MVAS')
        payout = Payout.objects.create(
            offer=self.offer, revenue='0.30', payout='0.30', goal_value='1',
            currency=Currency.objects.create(code='USD', name='USD'))
        payout.countries.add(Country.objects.create(iso='KE', iso3='KEN', iso_numeric=404, name='Kenya'))

    def _click(self, asn=33771, isp='Safaricom'):
        return Click.objects.create(
            ip='105.160.0.1', country='KE', asn=asn, isp=isp, revenue=0, payout=0,
            offer=self.offer, affiliate=self.aff)

    def _convert(self, click, **extra):
        conversion(dict({'click_id': click.id, 'goal': '1', 'sum': 0, 'status': 'approved'}, **extra))
        return Conversion.objects.filter(click_id=click.id).order_by('-created_at').first()

    def test_no_controls_keeps_existing_behaviour(self, *_):
        self.assertEqual(self._convert(self._click(asn=None)).status, 'approved')

    def test_allowed_carrier_is_approved(self, *_):
        self.offer.allowed_asns = 'AS33771, 36866'
        self.offer.save()
        self.assertEqual(self._convert(self._click()).status, 'approved')

    def test_other_carrier_is_rejected(self, *_):
        self.offer.allowed_asns = '33771'
        self.offer.save()
        cv = self._convert(self._click(asn=36926, isp='Airtel KE'))
        self.assertEqual(cv.status, 'rejected')
        self.assertEqual(cv.comment, 'Carrier not allowed (AS36926 Airtel KE)')

    def test_unknown_carrier_is_held(self, *_):
        self.offer.allowed_asns = '33771'
        self.offer.save()
        cv = self._convert(self._click(asn=None, isp=''))
        self.assertEqual((cv.status, cv.comment), ('hold', 'Carrier unknown - review'))

    def test_daily_cap_rejects_over_the_cap_and_ignores_rejected(self, *_):
        self.offer.daily_cap = 2
        self.offer.save()
        self.offer.allowed_asns = '33771'
        self.offer.save()
        self._convert(self._click(asn=1, isp='Other'))  # rejected: must not count
        statuses = [self._convert(self._click()).status for _ in range(3)]
        self.assertEqual(statuses, ['approved', 'approved', 'rejected'])
        self.assertEqual(
            Conversion.objects.filter(comment='Daily cap reached (2)').count(), 1)

    def test_txid_is_stored_and_deduped_per_offer(self, *_):
        first = self._convert(self._click(), txid='TX-1')
        second = self._convert(self._click(), txid='TX-1')
        self.assertEqual((first.status, first.txid), ('approved', 'TX-1'))
        self.assertEqual((second.status, second.comment), ('rejected', 'Duplicate txid'))

    def test_non_uuid_click_id_does_not_crash(self, *_):
        self.assertIn('Click not found', conversion({'click_id': '{rcid}', 'goal': '1', 'sum': 0}))


class IpLookupTests(TestCase):

    def test_parse_asn(self):
        self.assertEqual(parse_asn('AS33771 Safaricom Limited'), 33771)
        self.assertIsNone(parse_asn(''))
        self.assertIsNone(parse_asn('Safaricom'))

    @mock.patch('tracker.tasks.click.geoip.country_code', return_value='KE')
    @mock.patch('tracker.tasks.click.API')
    def test_falls_back_to_geolite_when_ip_api_fails(self, api, _geo):
        api.return_value.query.side_effect = Err()
        self.assertEqual(lookup_ip('105.160.0.1'), Response(country_code='KE'))

    @mock.patch('tracker.tasks.click.API')
    def test_uses_ip_api_network_fields(self, api):
        api.return_value.query.return_value = Response('KE', 33771, 'Safaricom', True)
        self.assertEqual(lookup_ip('105.160.0.1').asn, 33771)
