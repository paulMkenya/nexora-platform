"""Inbound webhooks for M-Pesa B2C result and NOWPayments IPN."""
import json
import logging

from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

logger = logging.getLogger(__name__)


@csrf_exempt
@require_http_methods(['POST'])
def mpesa_b2c_callback(request):
    """
    Safaricom Daraja B2C result URL.
    Updates PayoutRequest status based on ConversationID.
    """
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return HttpResponse('Bad JSON', status=400)

    result = body.get('Result', {})
    conversation_id = result.get('ConversationID', '')
    result_code = result.get('ResultCode', -1)

    if not conversation_id:
        return JsonResponse({'status': 'ignored'})

    _update_request_from_mpesa(conversation_id, result_code)
    return JsonResponse({'status': 'ok'})


def _update_request_from_mpesa(conversation_id: str, result_code: int):
    from payouts.models import PayoutRequest, STATUS_PAID, STATUS_FAILED
    from django.utils import timezone

    try:
        req = PayoutRequest.objects.get(tx_ref=conversation_id)
    except PayoutRequest.DoesNotExist:
        logger.warning('mpesa callback: no PayoutRequest with tx_ref=%s', conversation_id)
        return

    if result_code == 0:
        req.status = STATUS_PAID
        req.paid_at = timezone.now()
    else:
        req.status = STATUS_FAILED
        req.notes = f'Daraja ResultCode={result_code}'
    req.save(update_fields=['status', 'paid_at', 'notes', 'updated_at'])


@csrf_exempt
@require_http_methods(['POST'])
def nowpayments_ipn(request):
    """NOWPayments IPN webhook (server-to-server; CSRF-exempt, signature-gated).

    FAIL-CLOSED: the HMAC-SHA512 signature over the raw body is verified FIRST and
    nothing is trusted until it passes. On success the (now-trusted) payload is
    handed to a Celery task and we return 200 immediately — no heavy work in the
    request. Processing is idempotent, so a replayed IPN is a no-op.
    """
    from django.conf import settings
    from payouts.providers.nowpayments.ipn import verify_ipn_signature

    sig = request.headers.get('x-nowpayments-sig', '')
    raw = request.body
    secret = getattr(settings, 'NOWPAYMENTS_IPN_SECRET', '')

    if not verify_ipn_signature(raw, sig, secret):
        logger.warning('NOWPayments IPN rejected: missing/invalid signature.')
        return HttpResponse('Invalid signature', status=401)

    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return HttpResponse('Bad JSON', status=400)

    from payouts.tasks.ipn import process_nowpayments_ipn
    process_nowpayments_ipn.delay(data)
    return JsonResponse({'status': 'ok'})
