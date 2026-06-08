"""Tests for M-Pesa B2C callback and NOWPayments IPN webhook."""
import hashlib
import hmac as _hmac
import json
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, Client, override_settings

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


@override_settings(NOWPAYMENTS_IPN_SECRET='ipnsecret123')
class NowPaymentsIPNTest(TestCase):
    """The webhook is a thin, fail-closed, signature-gated enqueuer. Signature
    canonicalization and async processing/idempotency are covered in
    ``test_nowpayments_ipn.py``; here we cover the HTTP gate + enqueue contract."""

    def setUp(self):
        self.client = Client()
        self.secret = 'ipnsecret123'

    def _sign(self, payload_dict) -> str:
        from payouts.providers.nowpayments.ipn import canonical_json
        return _hmac.new(
            self.secret.encode(), canonical_json(payload_dict).encode(),
            hashlib.sha512).hexdigest()

    def _post(self, payload_dict, sig):
        return self.client.post(
            '/webhooks/nowpayments/',
            data=json.dumps(payload_dict),
            content_type='application/json',
            HTTP_X_NOWPAYMENTS_SIG=sig,
        )

    def test_rejects_missing_signature(self):
        payload = {'id': 'w-1', 'status': 'finished', 'extra_id': '999'}
        r = self.client.post(
            '/webhooks/nowpayments/', data=json.dumps(payload),
            content_type='application/json')
        self.assertEqual(r.status_code, 401)

    def test_rejects_invalid_signature(self):
        payload = {'id': 'w-1', 'status': 'finished', 'extra_id': '999'}
        r = self._post(payload, 'badsig')
        self.assertEqual(r.status_code, 401)

    @patch('payouts.tasks.ipn.process_nowpayments_ipn.delay')
    def test_valid_signature_enqueues_and_returns_200(self, delay):
        payload = {'id': 'w-1', 'status': 'finished', 'extra_id': '999'}
        r = self._post(payload, self._sign(payload))
        self.assertEqual(r.status_code, 200)
        delay.assert_called_once_with(payload)

    @patch('payouts.tasks.ipn.process_nowpayments_ipn.delay')
    def test_invalid_signature_does_not_enqueue(self, delay):
        payload = {'id': 'w-1', 'status': 'finished', 'extra_id': '999'}
        self._post(payload, 'badsig')
        delay.assert_not_called()
