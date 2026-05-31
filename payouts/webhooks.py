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
    """
    NOWPayments IPN webhook.
    Verifies HMAC-SHA512 signature, updates PayoutRequest status.
    """
    from payouts.crypto.nowpayments import NowPaymentsProvider

    sig = request.headers.get('x-nowpayments-sig', '')
    payload = request.body
    provider = NowPaymentsProvider()

    if not provider.verify_ipn(payload, sig):
        logger.warning('NOWPayments IPN signature mismatch')
        return HttpResponse('Invalid signature', status=401)

    try:
        data = json.loads(payload)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return HttpResponse('Bad JSON', status=400)

    payment_id = str(data.get('payment_id', ''))
    payment_status = data.get('payment_status', '')
    extra_id = str(data.get('extra_id', ''))

    _update_request_from_nowpayments(extra_id, payment_id, payment_status)
    return JsonResponse({'status': 'ok'})


def _update_request_from_nowpayments(extra_id: str, payment_id: str, payment_status: str):
    from payouts.models import PayoutRequest, STATUS_PAID, STATUS_FAILED, STATUS_PROCESSING
    from django.utils import timezone

    if not extra_id:
        return

    try:
        req = PayoutRequest.objects.get(pk=int(extra_id))
    except (PayoutRequest.DoesNotExist, ValueError):
        logger.warning('NOWPayments IPN: no PayoutRequest pk=%s', extra_id)
        return

    if payment_status in ('finished', 'confirmed'):
        req.status = STATUS_PAID
        req.paid_at = timezone.now()
        if payment_id:
            req.tx_ref = payment_id
    elif payment_status in ('failed', 'refunded', 'expired'):
        req.status = STATUS_FAILED
        req.notes = f'NOWPayments status={payment_status}'
    else:
        req.status = STATUS_PROCESSING
    req.save(update_fields=['status', 'paid_at', 'tx_ref', 'notes', 'updated_at'])
