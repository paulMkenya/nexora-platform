"""Tests for the payout generation task: threshold gating and double-payout prevention."""
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from offer.models import Offer, Advertiser
from tracker.models import Conversion, APPROVED_STATUS, REJECTED_STATUS
from payouts.models import PayoutRequest, PayoutSettings, PayoutMethod, METHOD_PAYPAL
from payouts.tasks.generate import generate_payout_requests
from payouts.services import get_unpaid_earnings

User = get_user_model()


def _make_affiliate(username='aff1'):
    return User.objects.create_user(username=username, password='pass')


def _make_advertiser():
    user = User.objects.create_user(username='advtask', password='pass')
    return Advertiser.objects.create(user=user, company='TaskAdv', email='adv@task.com')


def _make_offer(advertiser):
    return Offer.objects.create(
        title='Task Offer', advertiser=advertiser,
        tracking_link='http://example.com',
    )


def _make_conversion(affiliate, offer, payout, status=APPROVED_STATUS, days_ago=0):
    from django.utils import timezone
    ts = timezone.now() - timedelta(days=days_ago)
    c = Conversion.objects.create(
        affiliate=affiliate,
        offer=offer,
        payout=Decimal(str(payout)),
        revenue=Decimal(str(payout)),
        status=status,
    )
    Conversion.objects.filter(pk=c.pk).update(created_at=ts)
    return c


class EarningsHelperTest(TestCase):
    def setUp(self):
        self.affiliate = _make_affiliate('earnuser')
        adv = _make_advertiser()
        self.offer = _make_offer(adv)

    def test_approved_conversions_included(self):
        _make_conversion(self.affiliate, self.offer, '75.00', APPROVED_STATUS)
        earnings = get_unpaid_earnings(self.affiliate, date(2000, 1, 1), date.today())
        self.assertEqual(earnings, Decimal('75.00'))

    def test_rejected_conversions_excluded(self):
        _make_conversion(self.affiliate, self.offer, '50.00', REJECTED_STATUS)
        earnings = get_unpaid_earnings(self.affiliate, date(2000, 1, 1), date.today())
        self.assertEqual(earnings, Decimal('0.00'))

    def test_mixed_statuses(self):
        _make_conversion(self.affiliate, self.offer, '100.00', APPROVED_STATUS)
        _make_conversion(self.affiliate, self.offer, '40.00', REJECTED_STATUS)
        earnings = get_unpaid_earnings(self.affiliate, date(2000, 1, 1), date.today())
        self.assertEqual(earnings, Decimal('100.00'))

    def test_date_range_filter(self):
        _make_conversion(self.affiliate, self.offer, '100.00', APPROVED_STATUS, days_ago=20)
        earnings = get_unpaid_earnings(self.affiliate, date.today() - timedelta(days=5), date.today())
        self.assertEqual(earnings, Decimal('0.00'))

    def test_zero_when_no_conversions(self):
        earnings = get_unpaid_earnings(self.affiliate, date(2000, 1, 1), date.today())
        self.assertEqual(earnings, Decimal('0.00'))


class GeneratePayoutRequestsTaskTest(TestCase):
    def setUp(self):
        self.affiliate = _make_affiliate('genuser')
        adv = _make_advertiser()
        self.offer = _make_offer(adv)

    def test_creates_payout_when_threshold_met(self):
        _make_conversion(self.affiliate, self.offer, '100.00', APPROVED_STATUS, days_ago=20)
        PayoutSettings.objects.create(
            affiliate=self.affiliate,
            min_threshold=Decimal('50.00'),
            net_terms=15,
            paid_through=date.today() - timedelta(days=30),
        )
        generate_payout_requests()
        self.assertTrue(PayoutRequest.objects.filter(affiliate=self.affiliate).exists())

    def test_no_payout_below_threshold(self):
        _make_conversion(self.affiliate, self.offer, '10.00', APPROVED_STATUS, days_ago=20)
        PayoutSettings.objects.create(
            affiliate=self.affiliate,
            min_threshold=Decimal('50.00'),
            net_terms=15,
            paid_through=date.today() - timedelta(days=30),
        )
        generate_payout_requests()
        self.assertFalse(PayoutRequest.objects.filter(affiliate=self.affiliate).exists())

    def test_no_payout_within_net_terms(self):
        _make_conversion(self.affiliate, self.offer, '100.00', APPROVED_STATUS, days_ago=5)
        PayoutSettings.objects.create(
            affiliate=self.affiliate,
            min_threshold=Decimal('50.00'),
            net_terms=15,
            paid_through=date.today() - timedelta(days=10),
        )
        generate_payout_requests()
        self.assertFalse(PayoutRequest.objects.filter(affiliate=self.affiliate).exists())

    def test_idempotent_no_double_payout(self):
        """Running the task twice must not create two PayoutRequests for the same period."""
        _make_conversion(self.affiliate, self.offer, '100.00', APPROVED_STATUS, days_ago=20)
        PayoutSettings.objects.create(
            affiliate=self.affiliate,
            min_threshold=Decimal('50.00'),
            net_terms=15,
            paid_through=date.today() - timedelta(days=30),
        )
        generate_payout_requests()
        generate_payout_requests()
        self.assertEqual(PayoutRequest.objects.filter(affiliate=self.affiliate).count(), 1)

    def test_paid_through_updated_after_generation(self):
        _make_conversion(self.affiliate, self.offer, '100.00', APPROVED_STATUS, days_ago=20)
        ps = PayoutSettings.objects.create(
            affiliate=self.affiliate,
            min_threshold=Decimal('50.00'),
            net_terms=15,
            paid_through=date.today() - timedelta(days=30),
        )
        generate_payout_requests()
        ps.refresh_from_db()
        self.assertIsNotNone(ps.paid_through)
        self.assertGreater(ps.paid_through, date.today() - timedelta(days=30))

    def test_uses_default_payout_method(self):
        _make_conversion(self.affiliate, self.offer, '100.00', APPROVED_STATUS, days_ago=20)
        pm = PayoutMethod.objects.create(
            affiliate=self.affiliate, method=METHOD_PAYPAL,
            details={'email': 'aff@test.com'}, is_default=True,
        )
        PayoutSettings.objects.create(
            affiliate=self.affiliate,
            min_threshold=Decimal('50.00'),
            net_terms=15,
            paid_through=date.today() - timedelta(days=30),
        )
        generate_payout_requests()
        req = PayoutRequest.objects.get(affiliate=self.affiliate)
        self.assertEqual(req.payout_method, pm)
