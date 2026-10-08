"""seed_cloudtrade_offer: idempotent, visible to the brand's affiliates, pays
$10 on a Kenyan goal-1 postback, and never prints the HMAC secret."""
import os
import stat
import tempfile
from io import StringIO
from unittest import mock

from countries_plus.models import Country
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

from affiliate_ui.views.general_views import offers_for_affiliate
from brands.models import Brand
from offer.management.commands import seed_cloudtrade_offer as seed
from offer.models import Advertiser, AdvertiserPostbackKey, Goal, Offer, Payout
from tracker.models import PENDING_STATUS, REJECTED_STATUS, Click, Conversion
from tracker.tasks.conversion import conversion
from user_profile.models import Profile

User = get_user_model()


@mock.patch('offer.tasks.cache_offers.cache_offers', lambda: None)
class SeedCloudtradeOfferTests(TestCase):
    def setUp(self):
        Country.objects.get_or_create(
            iso='KE', defaults={'name': 'Kenya', 'iso3': 'KEN', 'iso_numeric': 404})
        Country.objects.get_or_create(
            iso='US', defaults={'name': 'United States', 'iso3': 'USA', 'iso_numeric': 840})
        self.brand = Brand.objects.get(slug=seed.BRAND_SLUG)

    def _run(self, *args):
        out = StringIO()
        call_command('seed_cloudtrade_offer', *args, stdout=out)
        return out.getvalue()

    def _offer(self):
        return Offer.objects.get(brand=self.brand, title=seed.OFFER_TITLE)

    def test_idempotent(self):
        self._run()
        self._run()
        offer = self._offer()
        self.assertEqual(Advertiser.objects.filter(email=seed.ADVERTISER_EMAIL).count(), 1)
        self.assertEqual(Goal.objects.filter(name=seed.GOAL_NAME).count(), 1)
        self.assertEqual(offer.landings.count(), 2)
        self.assertEqual(offer.payouts.count(), 1)
        self.assertEqual(AdvertiserPostbackKey.objects.filter(advertiser=offer.advertiser).count(), 1)

    def test_approves_an_existing_unverified_advertiser(self):
        Advertiser.objects.create(
            brand=self.brand, email=seed.ADVERTISER_EMAIL, company='Cloudtrade LTD',
            advertiser_status=Advertiser.AdvertiserStatus.PENDING, email_verified=False)
        self._run()
        adv = Advertiser.objects.get(email=seed.ADVERTISER_EMAIL)
        self.assertTrue(adv.is_active_advertiser)
        self.assertEqual(adv.company, 'Cloudtrade Centralised Systems Ltd')

    def test_offer_and_payout_shape(self):
        self._run()
        offer = self._offer()
        self.assertEqual(offer.tracking_link,
                         'https://cloudtrade.pro/?click_id={click_id}&pid={pid}')
        self.assertEqual(offer.targeting_display(), 'KE only')
        p = Payout.objects.get(offer=offer)
        self.assertEqual((p.goal_value, str(p.payout), str(p.revenue), p.currency.code),
                         ('1', '10.00', '10.00', 'USD'))
        self.assertEqual(p.goal.name, seed.GOAL_NAME)
        self.assertEqual(list(p.countries.values_list('iso', flat=True)), ['KE'])

    def test_visible_to_brand_affiliate(self):
        self._run()
        aff = User.objects.create(username='aff')
        aff.profile.brand = self.brand
        aff.profile.role = Profile.Role.AFFILIATE
        aff.profile.save()
        self.assertIn(self._offer(), offers_for_affiliate(aff))

    def _click(self, country):
        aff = User.objects.create(username=f'aff-{country}')
        return Click.objects.create(
            offer=self._offer(), affiliate=aff, brand=self.brand, ip='41.90.0.1',
            country=country, revenue=0, payout=0)

    def test_kenyan_postback_is_a_pending_ten_dollar_conversion(self):
        self._run()
        click = self._click('KE')
        with mock.patch('fraud.tasks.score_conversion_fraud.delay'), \
                mock.patch('billing.tasks.debit.debit_conversion.delay'):
            conversion({'click_id': str(click.id), 'goal': '1', 'sum': 0.0,
                        'status': PENDING_STATUS})
        conv = Conversion.objects.get(click_id=click.id)
        self.assertEqual((conv.status, str(conv.payout), conv.currency.code),
                         (PENDING_STATUS, '10.00', 'USD'))

    def test_non_kenyan_click_finds_no_payout(self):
        self._run()
        click = self._click('US')
        with mock.patch('fraud.tasks.score_conversion_fraud.delay'), \
                mock.patch('billing.tasks.debit.debit_conversion.delay'):
            conversion({'click_id': str(click.id), 'goal': '1', 'sum': 0.0,
                        'status': PENDING_STATUS})
        conv = Conversion.objects.get(click_id=click.id)
        self.assertEqual((conv.status, conv.comment), (REJECTED_STATUS, 'Payout not found'))

    def test_secret_goes_to_a_private_file_and_never_to_stdout(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'secret')
            out = self._run('--secret-file', path)
            secret = AdvertiserPostbackKey.objects.get().secret
            self.assertNotIn(secret, out)
            with open(path) as fh:
                self.assertEqual(fh.read().strip(), secret)
            self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)

    def test_rerun_keeps_key_unless_rotated(self):
        self._run()
        first = AdvertiserPostbackKey.objects.get().secret
        self._run()
        self.assertEqual(AdvertiserPostbackKey.objects.get().secret, first)
        self._run('--rotate-key')
        self.assertNotEqual(AdvertiserPostbackKey.objects.get().secret, first)
