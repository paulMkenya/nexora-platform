"""
Tests: Stripe + Paystack webhook signature validation and feature-flag behaviour.
"""
import hashlib
import hmac
import json
import time
import pytest
from unittest import mock

from django.test import Client, override_settings


def _stripe_sig(payload: bytes, secret: str, ts: int = None) -> str:
    ts = ts or int(time.time())
    signed = f'{ts}.'.encode() + payload
    v1 = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return f't={ts},v1={v1}'


def _paystack_sig(payload: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), payload, hashlib.sha512).hexdigest()


STRIPE_URL = '/webhooks/stripe/'
PAYSTACK_URL = '/webhooks/paystack/'


# ── Stripe ────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestStripeWebhook:

    def test_feature_flagged_off_returns_200(self):
        c = Client()
        with override_settings(STRIPE_SECRET_KEY='', STRIPE_WEBHOOK_SECRET=''):
            resp = c.post(STRIPE_URL, data=b'{}', content_type='application/json')
        assert resp.status_code == 200

    def test_valid_signature_accepted(self):
        secret = 'whsec_test123'
        payload = json.dumps({'type': 'payment_intent.succeeded',
                              'data': {'object': {'id': 'pi_test', 'amount': 5000,
                                                  'metadata': {'wallet_id': '1'}}}}).encode()
        sig = _stripe_sig(payload, secret)
        c = Client()
        with override_settings(STRIPE_SECRET_KEY='sk_test', STRIPE_WEBHOOK_SECRET=secret):
            with mock.patch('billing.tasks.topup.process_topup.delay'):
                resp = c.post(STRIPE_URL, data=payload, content_type='application/json',
                              HTTP_STRIPE_SIGNATURE=sig)
        assert resp.status_code == 200

    def test_invalid_signature_rejected(self):
        secret = 'whsec_real'
        payload = b'{"type": "payment_intent.succeeded"}'
        bad_sig = _stripe_sig(payload, 'whsec_wrong')
        c = Client()
        with override_settings(STRIPE_SECRET_KEY='sk_test', STRIPE_WEBHOOK_SECRET=secret):
            resp = c.post(STRIPE_URL, data=payload, content_type='application/json',
                          HTTP_STRIPE_SIGNATURE=bad_sig)
        assert resp.status_code == 400

    def test_stale_timestamp_rejected(self):
        secret = 'whsec_test'
        payload = b'{"type": "ping"}'
        old_ts = int(time.time()) - 400  # older than 300s
        sig = _stripe_sig(payload, secret, ts=old_ts)
        c = Client()
        with override_settings(STRIPE_SECRET_KEY='sk_test', STRIPE_WEBHOOK_SECRET=secret):
            resp = c.post(STRIPE_URL, data=payload, content_type='application/json',
                          HTTP_STRIPE_SIGNATURE=sig)
        assert resp.status_code == 400

    def test_unknown_event_type_returns_200(self):
        secret = 'whsec_ok'
        payload = json.dumps({'type': 'customer.created'}).encode()
        sig = _stripe_sig(payload, secret)
        c = Client()
        with override_settings(STRIPE_SECRET_KEY='sk_test', STRIPE_WEBHOOK_SECRET=secret):
            resp = c.post(STRIPE_URL, data=payload, content_type='application/json',
                          HTTP_STRIPE_SIGNATURE=sig)
        assert resp.status_code == 200

    def test_get_not_allowed(self):
        c = Client()
        resp = c.get(STRIPE_URL)
        assert resp.status_code == 405


# ── Paystack ──────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestPaystackWebhook:

    def test_feature_flagged_off_returns_200(self):
        c = Client()
        with override_settings(PAYSTACK_SECRET_KEY=''):
            resp = c.post(PAYSTACK_URL, data=b'{}', content_type='application/json')
        assert resp.status_code == 200

    def test_valid_signature_accepted(self):
        secret = 'ps_live_secret'
        payload = json.dumps({
            'event': 'charge.success',
            'data': {'reference': 'txn_abc', 'amount': 100000,
                     'metadata': {'wallet_id': '1'}},
        }).encode()
        sig = _paystack_sig(payload, secret)
        c = Client()
        with override_settings(PAYSTACK_SECRET_KEY=secret):
            with mock.patch('billing.tasks.topup.process_topup.delay'):
                resp = c.post(PAYSTACK_URL, data=payload, content_type='application/json',
                              HTTP_X_PAYSTACK_SIGNATURE=sig)
        assert resp.status_code == 200

    def test_invalid_signature_rejected(self):
        secret = 'ps_real_secret'
        payload = b'{"event": "charge.success"}'
        bad_sig = _paystack_sig(payload, 'ps_wrong_secret')
        c = Client()
        with override_settings(PAYSTACK_SECRET_KEY=secret):
            resp = c.post(PAYSTACK_URL, data=payload, content_type='application/json',
                          HTTP_X_PAYSTACK_SIGNATURE=bad_sig)
        assert resp.status_code == 400

    def test_unknown_event_returns_200(self):
        secret = 'ps_secret'
        payload = json.dumps({'event': 'subscription.create'}).encode()
        sig = _paystack_sig(payload, secret)
        c = Client()
        with override_settings(PAYSTACK_SECRET_KEY=secret):
            resp = c.post(PAYSTACK_URL, data=payload, content_type='application/json',
                          HTTP_X_PAYSTACK_SIGNATURE=sig)
        assert resp.status_code == 200

    def test_get_not_allowed(self):
        c = Client()
        resp = c.get(PAYSTACK_URL)
        assert resp.status_code == 405
