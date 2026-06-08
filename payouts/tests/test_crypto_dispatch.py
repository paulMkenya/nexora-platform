"""Tests for wiring the NOWPayments client beneath the control layer (PR #11).

All provider calls are mocked — CI never touches the network. Covers:
  * the CRYPTO_DISPATCH_ENABLED kill-switch (no-op off / dispatches on),
  * the NOWPAYMENTS_ALLOW_MAINNET guard refusing a production URL,
  * outbound idempotency (an already-dispatched request never re-creates a batch),
  * the CRITICAL composition test: a blocked/held payout NEVER reaches the client.
"""
from decimal import Decimal
from unittest import mock
from unittest.mock import MagicMock

from django.test import TestCase, override_settings

from brands.models import Brand
from payouts.models import (
    CryptoPayoutBatch, PayoutMethod, PayoutRequest, WithdrawalControlConfig,
    METHOD_CRYPTO, STATUS_APPROVED, STATUS_BLOCKED, STATUS_FAILED,
    STATUS_PENDING_APPROVAL, STATUS_PROCESSING,
)
from payouts.providers.nowpayments import NowPaymentsPayoutClient
from user_profile.models import Profile, User

PROD_URL = 'https://api.nowpayments.io/v1'
SANDBOX_URL = 'https://api-sandbox.nowpayments.io/v1'


def _ok_client():
    """A spec'd NOWPayments client mock whose create+verify succeed."""
    client = MagicMock(spec=NowPaymentsPayoutClient)
    client.create_payout.return_value = {'id': 'batch-1', 'withdrawals': [{'id': 'wd-1'}]}
    client.verify_payout.return_value = {'status': 'verified'}
    return client


class CryptoDispatchBase(TestCase):
    _seq = 0

    def setUp(self):
        self.brand = Brand.objects.create(
            slug='cd', name='CD', primary_domain='cd.test', tracking_domain='t.cd.test')
        self.cfg = WithdrawalControlConfig.load()
        # Generous defaults — each test tightens only the knob it exercises.
        self.cfg.enabled = True
        self.cfg.per_tx_max = Decimal('100000')
        self.cfg.per_affiliate_day_count = 0
        self.cfg.per_affiliate_day_amount = Decimal('0')
        self.cfg.per_brand_day_count = 0
        self.cfg.per_brand_day_amount = Decimal('0')
        self.cfg.platform_day_count = 0
        self.cfg.platform_day_amount = Decimal('0')
        self.cfg.approval_threshold = Decimal('0')
        self.cfg.new_address_cooldown_hours = 0
        self.cfg.anomaly_multiple = Decimal('0')
        self.cfg.anomaly_burst_count = 0
        self.cfg.save()

    def _affiliate(self, username):
        u = User.objects.create_user(username, password='pass')
        p = u.profile
        p.role = Profile.Role.AFFILIATE
        p.brand = self.brand
        p.save()
        return u

    def _method(self, affiliate, network='USDT-TRC20'):
        type(self)._seq += 1
        return PayoutMethod.objects.create(
            affiliate=affiliate, method=METHOD_CRYPTO,
            details={'network': network, 'wallet_address': f'TX{self._seq:06d}'})

    def _request(self, affiliate, amount, *, method=None, status=STATUS_APPROVED, **kw):
        return PayoutRequest.objects.create(
            affiliate=affiliate, payout_method=method, amount=Decimal(str(amount)),
            method=METHOD_CRYPTO, status=status, **kw)


@override_settings(CRYPTO_PAYOUT_PROVIDER='nowpayments')
class KillSwitchTest(CryptoDispatchBase):
    @override_settings(CRYPTO_DISPATCH_ENABLED=False)
    @mock.patch('payouts.providers.dispatch.get_crypto_provider')
    def test_killswitch_off_is_noop_and_never_builds_provider(self, get_provider):
        from payouts.providers.dispatch import dispatch_payout
        aff = self._affiliate('k1')
        req = self._request(aff, 50, method=self._method(aff))
        ok = dispatch_payout(req)
        self.assertFalse(ok)
        # No provider was even constructed.
        get_provider.assert_not_called()
        # Status untouched; note clearly distinguishable from a real failure.
        self.assertEqual(req.status, STATUS_APPROVED)
        self.assertIn('disabled', req.notes)

    @override_settings(CRYPTO_DISPATCH_ENABLED=True)
    def test_killswitch_on_dispatches_via_client(self):
        from payouts.providers.dispatch import dispatch_payout
        aff = self._affiliate('k2')
        req = self._request(aff, Decimal('12.3456789'), method=self._method(aff))
        client = _ok_client()
        with mock.patch('payouts.providers.dispatch.get_crypto_provider', return_value=client):
            ok = dispatch_payout(req)
        self.assertTrue(ok)
        client.create_payout.assert_called_once()
        kwargs = client.create_payout.call_args.kwargs
        self.assertEqual(kwargs['currency'], 'usdttrc20')   # USDT-TRC20 -> usdttrc20
        self.assertEqual(kwargs['extra_id'], str(req.pk))
        client.verify_payout.assert_called_once_with('batch-1')
        req.refresh_from_db()
        self.assertEqual(req.status, STATUS_PROCESSING)
        self.assertEqual(req.provider_withdrawal_id, 'wd-1')
        self.assertIsNotNone(req.provider_batch_id)
        self.assertTrue(CryptoPayoutBatch.objects.filter(
            provider_batch_id='batch-1', status='verified').exists())


@override_settings(CRYPTO_PAYOUT_PROVIDER='nowpayments')
class MainnetGuardDispatchTest(CryptoDispatchBase):
    @override_settings(CRYPTO_DISPATCH_ENABLED=True,
                       NOWPAYMENTS_BASE_URL=PROD_URL, NOWPAYMENTS_ALLOW_MAINNET=False)
    def test_production_url_without_flag_refuses_to_dispatch(self):
        from payouts.providers.dispatch import dispatch_payout
        aff = self._affiliate('m1')
        req = self._request(aff, 50, method=self._method(aff))
        # The real client init raises ImproperlyConfigured; dispatch_payout catches it.
        ok = dispatch_payout(req)
        self.assertFalse(ok)
        self.assertEqual(req.status, STATUS_FAILED)  # in-memory; caller persists
        self.assertFalse(CryptoPayoutBatch.objects.exists())


@override_settings(CRYPTO_PAYOUT_PROVIDER='nowpayments', CRYPTO_DISPATCH_ENABLED=True)
class OutboundIdempotencyTest(CryptoDispatchBase):
    def test_existing_provider_ids_do_not_recreate_batch(self):
        from payouts.providers.dispatch import dispatch_payout
        aff = self._affiliate('i1')
        req = self._request(aff, 50, method=self._method(aff),
                            provider_withdrawal_id='wd-existing', status=STATUS_PROCESSING)
        client = _ok_client()
        with mock.patch('payouts.providers.dispatch.get_crypto_provider', return_value=client):
            ok = dispatch_payout(req)
        self.assertTrue(ok)
        client.create_payout.assert_not_called()   # never re-sent
        client.verify_payout.assert_not_called()
        self.assertFalse(CryptoPayoutBatch.objects.exists())


@override_settings(CRYPTO_PAYOUT_PROVIDER='nowpayments', CRYPTO_DISPATCH_ENABLED=True)
class ControlLayerCompositionTest(CryptoDispatchBase):
    """The control layer is the safety net: a blocked/held payout must never reach
    the provider. This is the critical money-safety test."""

    def test_blocked_over_cap_never_reaches_provider(self):
        from payouts.control import enforce_and_dispatch
        self.cfg.per_tx_max = Decimal('500')
        self.cfg.save()
        aff = self._affiliate('b1')
        req = self._request(aff, 600, method=self._method(aff))
        client = MagicMock(spec=NowPaymentsPayoutClient)
        with mock.patch('payouts.providers.dispatch.get_crypto_provider', return_value=client):
            out = enforce_and_dispatch(req)
        self.assertTrue(out.blocked)
        client.create_payout.assert_not_called()
        client.verify_payout.assert_not_called()
        req.refresh_from_db()
        self.assertEqual(req.status, STATUS_BLOCKED)
        self.assertIsNone(req.dispatched_at)

    def test_held_threshold_never_reaches_provider(self):
        from payouts.control import enforce_and_dispatch
        self.cfg.approval_threshold = Decimal('100')
        self.cfg.save()
        aff = self._affiliate('h1')
        req = self._request(aff, 500, method=self._method(aff))
        client = MagicMock(spec=NowPaymentsPayoutClient)
        with mock.patch('payouts.providers.dispatch.get_crypto_provider', return_value=client):
            out = enforce_and_dispatch(req)
        self.assertTrue(out.held)
        client.create_payout.assert_not_called()
        req.refresh_from_db()
        self.assertEqual(req.status, STATUS_PENDING_APPROVAL)

    def test_allowed_payout_reaches_client_and_dispatches(self):
        from payouts.control import enforce_and_dispatch
        aff = self._affiliate('ok1')
        req = self._request(aff, 50, method=self._method(aff))
        client = _ok_client()
        with mock.patch('payouts.providers.dispatch.get_crypto_provider', return_value=client):
            out = enforce_and_dispatch(req)
        self.assertTrue(out.allowed)
        client.create_payout.assert_called_once()
        req.refresh_from_db()
        self.assertEqual(req.status, STATUS_PROCESSING)
        self.assertIsNotNone(req.dispatched_at)
        self.assertEqual(req.provider_withdrawal_id, 'wd-1')
