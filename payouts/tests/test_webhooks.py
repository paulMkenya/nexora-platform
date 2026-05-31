"""Tests for M-Pesa B2C callback and NOWPayments IPN webhook."""
import hashlib
import hmac as _hmac
import json
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, Client

from payouts.models import PayoutRequest, STATUS_PAID, STATUS_FAILED, STATUS_PENDING, METHOD_PAYPAL

User = get_user_model()


def _make_payout_request(tx_ref='', status=STATUS_PENDING):
    user = User.objects.create_user(username=f'wh_user_{tx_ref or "x"}', password='pass')
    return PayoutRequest.objects.create(
        affiliate=user,
        amount=Decimal('100.00'),
        method=METHOD_PAYPAL,
        status=status,
        tx_ref=tx_ref,
    )


class MpesaB2CCallbackTest(TestCase):
    def setUp(self):
        self.client = Client()

    def test_rejects_get(self):
        r = self.client.get('/webhooks/mpesa/b2c/')
        self.assertEqual(r.status_code, 405)

    def test_marks_paid_on_result_code_zero(self):
        req = _make_payout_request(tx_ref='CONV123', status=STATUS_PENDING)
        payload = {
            'Result': {'ResultCode': 0, 'ConversationID': 'CONV123', 'ResultDesc': 'Success'}
        }
        r = self.client.post(
            '/webhooks/mpesa/b2c/',
            data=json.dumps(payload),
            content_type='application/json',
        )
        self.assertEqual(r.status_code, 200)
        req.refresh_from_db()
        self.assertEqual(req.status, STATUS_PAID)

    def test_marks_failed_on_nonzero_result_code(self):
        req = _make_payout_request(tx_ref='CONVFAIL', status=STATUS_PENDING)
        payload = {'Result': {'ResultCode': 1032, 'ConversationID': 'CONVFAIL', 'ResultDesc': 'Cancelled'}}
        self.client.post('/webhooks/mpesa/b2c/', data=json.dumps(payload), content_type='application/json')
        req.refresh_from_db()
        self.assertEqual(req.status, STATUS_FAILED)

    def test_ignores_unknown_conversation_id(self):
        payload = {'Result': {'ResultCode': 0, 'ConversationID': 'UNKNOWN999'}}
        r = self.client.post('/webhooks/mpesa/b2c/', data=json.dumps(payload), content_type='application/json')
        self.assertEqual(r.status_code, 200)

    def test_bad_json_returns_400(self):
        r = self.client.post('/webhooks/mpesa/b2c/', data='not-json', content_type='application/json')
        self.assertEqual(r.status_code, 400)


class NowPaymentsIPNTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.secret = 'ipnsecret123'

    def _sign(self, payload: bytes) -> str:
        return _hmac.new(self.secret.encode(), payload, hashlib.sha512).hexdigest()

    def test_rejects_invalid_signature(self):
        import unittest.mock as mock
        payload = json.dumps({'payment_id': '1', 'payment_status': 'finished', 'extra_id': '999'}).encode()
        with mock.patch.dict('os.environ', {'NOWPAYMENTS_IPN_SECRET': self.secret}):
            r = self.client.post(
                '/webhooks/nowpayments/',
                data=payload,
                content_type='application/json',
                HTTP_X_NOWPAYMENTS_SIG='badsig',
            )
        self.assertEqual(r.status_code, 401)

    def test_marks_paid_on_finished_status(self):
        user = User.objects.create_user(username='npwh1', password='pass')
        req = PayoutRequest.objects.create(
            affiliate=user, amount=Decimal('50.00'), method=METHOD_PAYPAL, status=STATUS_PENDING,
        )
        import unittest.mock as mock
        payload = json.dumps({
            'payment_id': 'NP_TXN_456', 'payment_status': 'finished', 'extra_id': str(req.pk)
        }).encode()
        sig = self._sign(payload)
        with mock.patch.dict('os.environ', {'NOWPAYMENTS_IPN_SECRET': self.secret}):
            r = self.client.post(
                '/webhooks/nowpayments/',
                data=payload,
                content_type='application/json',
                HTTP_X_NOWPAYMENTS_SIG=sig,
            )
        self.assertEqual(r.status_code, 200)
        req.refresh_from_db()
        self.assertEqual(req.status, STATUS_PAID)

    def test_marks_failed_on_failed_status(self):
        user = User.objects.create_user(username='npwh2', password='pass')
        req = PayoutRequest.objects.create(
            affiliate=user, amount=Decimal('50.00'), method=METHOD_PAYPAL, status=STATUS_PENDING,
        )
        import unittest.mock as mock
        payload = json.dumps({
            'payment_id': 'NP_TXN_FAIL', 'payment_status': 'failed', 'extra_id': str(req.pk)
        }).encode()
        sig = self._sign(payload)
        with mock.patch.dict('os.environ', {'NOWPAYMENTS_IPN_SECRET': self.secret}):
            self.client.post(
                '/webhooks/nowpayments/',
                data=payload,
                content_type='application/json',
                HTTP_X_NOWPAYMENTS_SIG=sig,
            )
        req.refresh_from_db()
        self.assertEqual(req.status, STATUS_FAILED)
