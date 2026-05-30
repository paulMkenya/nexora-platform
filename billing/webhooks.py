"""
Inbound webhook handlers for payment providers.

Both are feature-flagged: if the corresponding secret key is blank in settings,
the endpoint accepts all requests and returns 200 without processing.
"""
import hashlib
import hmac
import json
import time

from django.conf import settings
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST


# ── Stripe ────────────────────────────────────────────────────────────────────

def _verify_stripe_signature(payload: bytes, sig_header: str, secret: str) -> bool:
    """
    Stripe signs: '{timestamp}.{payload}' with HMAC-SHA256.
    Header format: 't=<ts>,v1=<hex_sig>[,v1=...]'
    """
    try:
        parts = {k: v for k, v in (item.split('=', 1) for item in sig_header.split(','))}
        ts = parts.get('t', '')
        v1 = parts.get('v1', '')
        signed = f'{ts}.'.encode() + payload
        expected = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(v1, expected):
            return False
        # Reject events older than 5 minutes
        if abs(time.time() - int(ts)) > 300:
            return False
        return True
    except Exception:
        return False


@csrf_exempt
@require_POST
def stripe_webhook(request):
    secret_key = getattr(settings, 'STRIPE_SECRET_KEY', '')
    webhook_secret = getattr(settings, 'STRIPE_WEBHOOK_SECRET', '')

    if not secret_key:
        return HttpResponse('OK')  # feature-flagged off

    sig_header = request.META.get('HTTP_STRIPE_SIGNATURE', '')
    if webhook_secret and not _verify_stripe_signature(request.body, sig_header, webhook_secret):
        return HttpResponse('Invalid signature', status=400)

    try:
        event = json.loads(request.body)
    except json.JSONDecodeError:
        return HttpResponse('Bad JSON', status=400)

    if event.get('type') == 'payment_intent.succeeded':
        pi = event.get('data', {}).get('object', {})
        ext_ref = pi.get('id', '')
        wallet_id = pi.get('metadata', {}).get('wallet_id')
        # amount is in smallest currency unit (cents); convert to dollars
        raw_amount = pi.get('amount', 0)
        if wallet_id and ext_ref:
            from billing.tasks.topup import process_topup
            process_topup.delay(wallet_id, str(raw_amount / 100), 'stripe', ext_ref)

    return HttpResponse('OK')


# ── Paystack ──────────────────────────────────────────────────────────────────

def _verify_paystack_signature(payload: bytes, sig_header: str, secret: str) -> bool:
    expected = hmac.new(secret.encode(), payload, hashlib.sha512).hexdigest()
    return hmac.compare_digest(sig_header, expected)


@csrf_exempt
@require_POST
def paystack_webhook(request):
    secret_key = getattr(settings, 'PAYSTACK_SECRET_KEY', '')

    if not secret_key:
        return HttpResponse('OK')  # feature-flagged off

    sig_header = request.META.get('HTTP_X_PAYSTACK_SIGNATURE', '')
    if not _verify_paystack_signature(request.body, sig_header, secret_key):
        return HttpResponse('Invalid signature', status=400)

    try:
        event = json.loads(request.body)
    except json.JSONDecodeError:
        return HttpResponse('Bad JSON', status=400)

    if event.get('event') == 'charge.success':
        data = event.get('data', {})
        ext_ref = data.get('reference', '')
        wallet_id = data.get('metadata', {}).get('wallet_id')
        # Paystack amounts are in kobo (NGN) or pesewas (GHS); divide by 100
        raw_amount = data.get('amount', 0)
        if wallet_id and ext_ref:
            from billing.tasks.topup import process_topup
            process_topup.delay(wallet_id, str(raw_amount / 100), 'paystack', ext_ref)

    return HttpResponse('OK')
