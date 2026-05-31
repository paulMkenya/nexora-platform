"""Tests for PayoutMethod, PayoutRequest, PayoutSettings models."""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from payouts.models import (
    PayoutMethod, PayoutRequest, PayoutSettings,
    STATUS_PAID, STATUS_PENDING, METHOD_PAYPAL,
)

User = get_user_model()


def _user(username='testaffiliate'):
    return User.objects.create_user(username=username, password='pass')


class PayoutMethodDefaultTest(TestCase):
    def setUp(self):
        self.user = _user()

    def test_setting_default_clears_previous(self):
        m1 = PayoutMethod.objects.create(
            affiliate=self.user, method=METHOD_PAYPAL, details={'email': 'a@b.com'}, is_default=True,
        )
        m2 = PayoutMethod.objects.create(
            affiliate=self.user, method=METHOD_PAYPAL, details={'email': 'c@d.com'}, is_default=True,
        )
        m1.refresh_from_db()
        self.assertFalse(m1.is_default)
        self.assertTrue(m2.is_default)

    def test_multiple_non_default_allowed(self):
        PayoutMethod.objects.create(affiliate=self.user, method=METHOD_PAYPAL, details={'email': 'a@b.com'})
        PayoutMethod.objects.create(affiliate=self.user, method='wise', details={'email': 'c@d.com'})
        self.assertEqual(PayoutMethod.objects.filter(affiliate=self.user).count(), 2)


class PayoutRequestMarkPaidTest(TestCase):
    def setUp(self):
        self.user = _user('payuser')

    def test_mark_paid_sets_status_and_tx_ref(self):
        req = PayoutRequest.objects.create(
            affiliate=self.user, amount=Decimal('100.00'), method=METHOD_PAYPAL, status=STATUS_PENDING,
        )
        req.mark_paid(tx_ref='TXN123')
        req.refresh_from_db()
        self.assertEqual(req.status, STATUS_PAID)
        self.assertEqual(req.tx_ref, 'TXN123')
        self.assertIsNotNone(req.paid_at)

    def test_mark_paid_without_tx_ref(self):
        req = PayoutRequest.objects.create(
            affiliate=self.user, amount=Decimal('50.00'), method=METHOD_PAYPAL, status=STATUS_PENDING,
        )
        req.mark_paid()
        self.assertEqual(req.status, STATUS_PAID)
        self.assertEqual(req.tx_ref, '')


class PayoutSettingsTest(TestCase):
    def setUp(self):
        self.user = _user('settingsuser')

    def test_default_values(self):
        ps, _ = PayoutSettings.objects.get_or_create(affiliate=self.user)
        self.assertEqual(ps.min_threshold, Decimal('50.00'))
        self.assertEqual(ps.net_terms, 15)
        self.assertEqual(ps.schedule, 'monthly')
        self.assertIsNone(ps.paid_through)

    def test_unique_per_affiliate(self):
        PayoutSettings.objects.get_or_create(affiliate=self.user)
        PayoutSettings.objects.get_or_create(affiliate=self.user)
        self.assertEqual(PayoutSettings.objects.filter(affiliate=self.user).count(), 1)
