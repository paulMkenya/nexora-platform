"""
Webhook delivery task with HMAC-SHA256 signing and exponential backoff retries.

Delivery headers:
  X-Nexora-Event: <event_name>
  X-Nexora-Delivery: <delivery_pk>
  X-Nexora-Signature: sha256=<hmac_hex>

Retry schedule: 60s → 300s → 1800s (3 attempts total).
After 3 failures the delivery is marked 'failed' and no further retries occur.
"""
import hashlib
import hmac
import json
from datetime import timedelta

import requests as http_requests
from django.utils import timezone

from project._celery import _celery
from public_api.models import WebhookDelivery


def _sign(secret: str, payload_bytes: bytes) -> str:
    sig = hmac.new(secret.encode(), payload_bytes, hashlib.sha256).hexdigest()
    return f'sha256={sig}'


@_celery.task(bind=True, max_retries=3, ignore_result=True)
def deliver_webhook(self, delivery_id: int):
    try:
        delivery = WebhookDelivery.objects.select_related('endpoint').get(pk=delivery_id)
    except WebhookDelivery.DoesNotExist:
        return

    if delivery.status == WebhookDelivery.STATUS_DELIVERED:
        return

    endpoint = delivery.endpoint
    payload_bytes = json.dumps(delivery.payload, default=str).encode()
    signature = _sign(endpoint.secret, payload_bytes)

    delivery.attempts += 1
    attempt = delivery.attempts

    try:
        resp = http_requests.post(
            endpoint.url,
            data=payload_bytes,
            headers={
                'Content-Type': 'application/json',
                'X-Nexora-Event': delivery.event,
                'X-Nexora-Delivery': str(delivery.pk),
                'X-Nexora-Signature': signature,
            },
            timeout=10,
        )
        resp.raise_for_status()
        delivery.status = WebhookDelivery.STATUS_DELIVERED
        delivery.delivered_at = timezone.now()
        delivery.last_error = ''
    except Exception as exc:
        delivery.last_error = str(exc)[:500]
        backoffs = WebhookDelivery.RETRY_BACKOFFS
        if attempt < len(backoffs):
            delivery.next_retry_at = timezone.now() + timedelta(seconds=backoffs[attempt - 1])
            delivery.save(update_fields=['attempts', 'last_error', 'next_retry_at'])
            raise self.retry(exc=exc, countdown=backoffs[attempt - 1])
        delivery.status = WebhookDelivery.STATUS_FAILED

    delivery.save(update_fields=['attempts', 'status', 'delivered_at', 'last_error', 'next_retry_at'])


def dispatch_webhook_event(brand_id: int, event: str, payload: dict):
    """Create WebhookDelivery rows and enqueue delivery tasks for every active endpoint."""
    from public_api.models import WebhookEndpoint

    endpoints = WebhookEndpoint.for_event(brand_id, event)
    for endpoint in endpoints:
        delivery = WebhookDelivery.objects.create(
            endpoint=endpoint,
            event=event,
            payload=payload,
        )
        deliver_webhook.delay(delivery.pk)
