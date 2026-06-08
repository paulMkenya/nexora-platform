"""Tests for NOWPayments IPN signature verification + async processing (PR #11).

Two layers:
  * the canonicalization + HMAC-SHA512 signature check (fail-closed), and
  * the idempotent Celery processor that maps IPN status onto PayoutRequest /
    CryptoPayoutBatch. No network is touched.
"""
import hashlib
import hmac
import json
from decimal import Decimal

from django.test import SimpleTestCase, TestCase

from payouts.models import (
    CryptoPayoutBatch, NowPaymentsIPNEvent, PayoutRequest,
    METHOD_CRYPTO, STATUS_FAILED, STATUS_PAID, STATUS_PROCESSING,
)
from payouts.providers.nowpayments.ipn import canonical_json, verify_ipn_signature
from payouts.tasks.ipn import process_nowpayments_ipn
from user_profile.models import User

SECRET = 'ipn-secret'


def _sig(payload_dict, secret=SECRET):
    return hmac.new(
        secret.encode(), canonical_json(payload_dict).encode(), hashlib.sha512).hexdigest()


class CanonicalJsonTest(SimpleTestCase):
    def test_sorts_keys_recursively(self):
        out = canonical_json({'b': 1, 'a': {'d': 2, 'c': 3}})
        self.assertEqual(out, '{"a":{"c":3,"d":2},"b":1}')

    def test_escapes_forward_slashes_like_php_json_encode(self):
        # A value with slashes (e.g. an ipn_callback_url) must come out escaped.
        out = canonical_json({'url': 'https://x.test/ipn'})
        self.assertEqual(out, '{"url":"https:\\/\\/x.test\\/ipn"}')

    def test_compact_separators_no_whitespace(self):
        self.assertEqual(canonical_json({'a': 1, 'b': 2}), '{"a":1,"b":2}')


class VerifyIpnSignatureTest(SimpleTestCase):
    def test_valid_signature_passes(self):
        payload = {'id': 'w', 'status': 'finished'}
        raw = json.dumps(payload).encode()
        self.assertTrue(verify_ipn_signature(raw, _sig(payload), SECRET))

    def test_unsorted_raw_body_still_verifies(self):
        # Server canonicalizes from the PARSED body, so key order in the raw bytes
        # we receive is irrelevant — only content matters.
        payload = {'id': 'w', 'status': 'finished'}
        raw = b'{"status":"finished","id":"w"}'
        self.assertTrue(verify_ipn_signature(raw, _sig(payload), SECRET))

    def test_wrong_signature_rejected(self):
        raw = json.dumps({'id': 'w', 'status': 'finished'}).encode()
        self.assertFalse(verify_ipn_signature(raw, 'deadbeef', SECRET))

    def test_empty_signature_rejected(self):
        raw = json.dumps({'id': 'w'}).encode()
        self.assertFalse(verify_ipn_signature(raw, '', SECRET))

    def test_empty_secret_rejected(self):
        payload = {'id': 'w'}
        self.assertFalse(verify_ipn_signature(json.dumps(payload).encode(), _sig(payload), ''))

    def test_non_json_body_rejected(self):
        self.assertFalse(verify_ipn_signature(b'not-json', 'whatever', SECRET))

    def test_wrong_secret_rejected(self):
        payload = {'id': 'w', 'status': 'finished'}
        raw = json.dumps(payload).encode()
        self.assertFalse(verify_ipn_signature(raw, _sig(payload, 'other-secret'), SECRET))


class IPNProcessingTest(TestCase):
    _seq = 0

    def _req(self, *, status=STATUS_PROCESSING, **kw):
        type(self)._seq += 1
        user = User.objects.create_user(f'ipn{self._seq}', password='pass')
        return PayoutRequest.objects.create(
            affiliate=user, amount=Decimal('50.00'), method=METHOD_CRYPTO,
            status=status, **kw)

    def test_finished_marks_paid_via_extra_id(self):
        req = self._req()
        process_nowpayments_ipn.apply(args=[{
            'id': 'wd-1', 'status': 'finished', 'extra_id': str(req.pk), 'hash': '0xabc'}])
        req.refresh_from_db()
        self.assertEqual(req.status, STATUS_PAID)
        self.assertEqual(req.tx_hash, '0xabc')
        self.assertEqual(req.provider_status, 'finished')
        self.assertIsNotNone(req.paid_at)

    def test_failed_status_marks_failed(self):
        req = self._req()
        process_nowpayments_ipn.apply(args=[{
            'id': 'wd-2', 'status': 'failed', 'extra_id': str(req.pk)}])
        req.refresh_from_db()
        self.assertEqual(req.status, STATUS_FAILED)

    def test_intermediate_status_maps_processing(self):
        req = self._req(status=STATUS_PROCESSING)
        process_nowpayments_ipn.apply(args=[{
            'id': 'wd-3', 'status': 'sending', 'extra_id': str(req.pk)}])
        req.refresh_from_db()
        self.assertEqual(req.status, STATUS_PROCESSING)
        self.assertEqual(req.provider_status, 'sending')

    def test_correlation_by_provider_withdrawal_id(self):
        req = self._req(provider_withdrawal_id='wd-9')
        # No extra_id — must correlate on the stored withdrawal id.
        process_nowpayments_ipn.apply(args=[{'id': 'wd-9', 'status': 'finished'}])
        req.refresh_from_db()
        self.assertEqual(req.status, STATUS_PAID)

    def test_replayed_ipn_is_idempotent_noop(self):
        req = self._req()
        payload = {'id': 'wd-7', 'status': 'finished', 'extra_id': str(req.pk), 'hash': '0xh'}
        process_nowpayments_ipn.apply(args=[payload])
        req.refresh_from_db()
        self.assertEqual(req.status, STATUS_PAID)

        # Tamper with the row, replay the SAME IPN: it must not re-apply.
        req.status = STATUS_PROCESSING
        req.save(update_fields=['status'])
        process_nowpayments_ipn.apply(args=[payload])
        req.refresh_from_db()
        self.assertEqual(req.status, STATUS_PROCESSING)  # untouched by the replay
        self.assertEqual(NowPaymentsIPNEvent.objects.count(), 1)

    def test_distinct_status_for_same_withdrawal_processes(self):
        req = self._req(status=STATUS_PROCESSING)
        process_nowpayments_ipn.apply(args=[{
            'id': 'wd-5', 'status': 'sending', 'extra_id': str(req.pk)}])
        process_nowpayments_ipn.apply(args=[{
            'id': 'wd-5', 'status': 'finished', 'extra_id': str(req.pk)}])
        req.refresh_from_db()
        self.assertEqual(req.status, STATUS_PAID)
        self.assertEqual(NowPaymentsIPNEvent.objects.count(), 2)

    def test_batch_status_mirrored(self):
        batch = CryptoPayoutBatch.objects.create(
            provider='nowpayments', provider_batch_id='batch-77', status='verified',
            currency='usdttrc20', total_amount=Decimal('50'))
        req = self._req(provider_batch=batch, provider_withdrawal_id='wd-77')
        process_nowpayments_ipn.apply(args=[{
            'id': 'wd-77', 'status': 'finished', 'extra_id': str(req.pk)}])
        batch.refresh_from_db()
        self.assertEqual(batch.status, 'finished')
        self.assertIsNotNone(batch.finished_at)
        self.assertEqual(batch.raw_last_status.get('status'), 'finished')

    def test_unknown_request_logs_event_without_error(self):
        process_nowpayments_ipn.apply(args=[{'id': 'wd-x', 'status': 'finished', 'extra_id': '999999'}])
        self.assertTrue(NowPaymentsIPNEvent.objects.filter(withdrawal_id='wd-x').exists())

    def test_unusable_payload_creates_no_event(self):
        process_nowpayments_ipn.apply(args=[{'foo': 'bar'}])
        self.assertEqual(NowPaymentsIPNEvent.objects.count(), 0)
