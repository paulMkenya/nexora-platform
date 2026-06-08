"""Async processing of NOWPayments payout IPN callbacks.

The webhook view (``payouts.webhooks.nowpayments_ipn``) verifies the HMAC-SHA512
signature, then hands the raw (already-trusted) payload here so the request can
return 200 immediately. All the DB work — dedupe, correlation, status mapping —
happens in this task.

Inbound idempotency: every event is recorded in :class:`NowPaymentsIPNEvent`
keyed by ``(provider, withdrawal_id, status)`` via ``get_or_create``. A replayed
IPN finds the row already present and becomes a no-op — nothing is double-updated
or double-credited.
"""
import logging

from django.utils import timezone

from project._celery import _celery

logger = logging.getLogger(__name__)

# NOWPayments payout/withdrawal statuses → our internal PayoutRequest status.
_TERMINAL_PAID = {'finished', 'confirmed'}
_TERMINAL_FAILED = {'failed', 'rejected', 'refunded', 'expired'}


def _event_fields(payload: dict):
    """Extract ``(withdrawal_id, status, extra_id)`` from an IPN payload.

    Handles both the payout shape (``id`` + ``status``) and the payment shape
    (``payment_id`` + ``payment_status``) defensively.
    """
    status = str(payload.get('payment_status') or payload.get('status') or '')
    withdrawal_id = str(
        payload.get('id')
        or payload.get('payment_id')
        or payload.get('batch_withdrawal_id')
        or '')
    extra_id = str(payload.get('extra_id') or '')
    return withdrawal_id, status, extra_id


def _find_request(withdrawal_id: str, extra_id: str):
    """Correlate an IPN to its PayoutRequest.

    Prefer ``extra_id`` (the PayoutRequest pk we set on create), then the stored
    ``provider_withdrawal_id``, then the batch id.
    """
    from payouts.models import PayoutRequest

    if extra_id:
        try:
            return PayoutRequest.objects.get(pk=int(extra_id))
        except (PayoutRequest.DoesNotExist, ValueError):
            pass
    if withdrawal_id:
        req = PayoutRequest.objects.filter(provider_withdrawal_id=withdrawal_id).first()
        if req is not None:
            return req
        req = PayoutRequest.objects.filter(
            provider_batch__provider_batch_id=withdrawal_id).first()
        if req is not None:
            return req
    return None


@_celery.task(bind=True, max_retries=3)
def process_nowpayments_ipn(self, payload: dict):
    """Process one verified NOWPayments IPN payload. Idempotent; safe to replay."""
    from payouts.models import (
        NowPaymentsIPNEvent, STATUS_PAID, STATUS_FAILED, STATUS_PROCESSING,
    )

    withdrawal_id, status, extra_id = _event_fields(payload or {})
    # Dedupe key: the withdrawal id, falling back to extra_id so an empty id can't
    # collapse distinct payouts onto one (provider, '', status) row.
    dedupe_id = withdrawal_id or extra_id
    if not dedupe_id or not status:
        logger.warning('NOWPayments IPN: unusable payload (id=%r status=%r) — ignoring',
                       dedupe_id, status)
        return

    event, created = NowPaymentsIPNEvent.objects.get_or_create(
        provider='nowpayments', withdrawal_id=dedupe_id, status=status,
        defaults={'raw': payload})
    if not created:
        logger.info('NOWPayments IPN replay ignored (id=%s status=%s) — idempotent no-op.',
                    dedupe_id, status)
        return

    req = _find_request(withdrawal_id, extra_id)
    if req is None:
        logger.warning('NOWPayments IPN: no PayoutRequest for id=%s extra_id=%s (event %s logged)',
                       withdrawal_id, extra_id, event.pk)
        return

    prior = req.status
    tx_hash = payload.get('hash') or payload.get('payout_hash') or ''
    lowered = status.lower()

    if lowered in _TERMINAL_PAID:
        req.status = STATUS_PAID
        req.paid_at = timezone.now()
        if tx_hash:
            req.tx_hash = str(tx_hash)
    elif lowered in _TERMINAL_FAILED:
        req.status = STATUS_FAILED
        req.notes = f'NOWPayments IPN status={status}'
    else:
        req.status = STATUS_PROCESSING
    req.provider_status = status
    req.save()

    # Mirror the terminal state onto the batch for operator visibility.
    batch = req.provider_batch
    if batch is not None:
        batch.status = status
        batch.raw_last_status = payload
        if lowered in _TERMINAL_PAID or lowered in _TERMINAL_FAILED:
            batch.finished_at = timezone.now()
        batch.save(update_fields=['status', 'raw_last_status', 'finished_at'])

    logger.info('NOWPayments IPN applied to req %s: %s -> %s (provider status=%s).',
                req.pk, prior, req.status, status)
