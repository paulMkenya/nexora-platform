"""Affiliate postback delivery — the push half of the return path (Affiliate
Inbound API spec §5.1). Mirrors public_api.tasks.deliver_webhook's HMAC
signing + retry/backoff shape exactly (same 60s/300s/1800s schedule, same
"resolve the row, do the work, save the outcome" structure) — this is the
"reuse the outbound engine's retry logic" the spec asks for.

dispatch_postbacks_for_event() is called from exactly one place —
leadgen.status_sync.apply_status_change(), and only for events where
applied=True. A recorded-but-not-applied TESTING-phase buyer status must
never reach an affiliate's postback URL: nothing actually changed for them,
so nothing should fire.
"""
import hashlib
import hmac
import json
from datetime import timedelta

import requests
from django.utils import timezone

from project._celery import _celery


def _sign(secret: str, payload_bytes: bytes) -> str:
    return f'sha256={hmac.new(secret.encode(), payload_bytes, hashlib.sha256).hexdigest()}'


def _render_url(template, *, lead, event):
    """Substitute the spec's §5.1 macro set into a configured postback URL
    template. `payout` always renders blank — no per-lead conversion-value
    model exists anywhere in this build yet (offer.Payout is a revenue-model
    config, not a lead-level dollar amount); left blank rather than
    fabricated, and worth flagging if/when a real payout figure is wanted
    here."""
    macros = {
        'lead_id': str(lead.pk),
        'source_id': lead.source_id,
        'status': event.to_status,
        'status_time': event.created_at.isoformat(),
        'offer_id': str(lead.offer_id or ''),
        'payout': '',
    }
    result = template
    for key, value in macros.items():
        result = result.replace('{' + key + '}', value)
    return result


def dispatch_postbacks_for_event(event):
    """Enqueue a PostbackDelivery (+ Celery delivery task) for every active
    AffiliatePostbackConfig belonging to event.lead's affiliate that's
    subscribed to event.to_status. A no-op for a lead with no affiliate
    (nothing to notify) or an affiliate with no configured postbacks."""
    from .models import AffiliatePostbackConfig, PostbackDelivery

    lead = event.lead
    if not lead.affiliate_id:
        return

    configs = AffiliatePostbackConfig.objects.filter(affiliate_id=lead.affiliate_id, is_active=True)
    for config in configs:
        if not config.wants_status(event.to_status):
            continue
        delivery = PostbackDelivery.objects.create(
            config=config, status_event=event, url=_render_url(config.url, lead=lead, event=event))
        deliver_affiliate_postback.delay(delivery.pk)


@_celery.task(bind=True, max_retries=3, ignore_result=True)
def deliver_affiliate_postback(self, delivery_id: int):
    from .models import PostbackDelivery

    try:
        delivery = PostbackDelivery.objects.select_related(
            'config', 'status_event', 'status_event__lead').get(pk=delivery_id)
    except PostbackDelivery.DoesNotExist:
        return

    if delivery.status == PostbackDelivery.STATUS_DELIVERED:
        return

    event = delivery.status_event
    lead = event.lead
    payload = {
        'lead_id': lead.pk,
        'source_id': lead.source_id,
        'status': event.to_status,
        'status_time': event.created_at.isoformat(),
        # Ordering guard — spec §5.3: the affiliate's receiver ignores a
        # postback whose status_seq is lower than one it already saw for
        # this lead_id, so a late-arriving transient-retry postback can
        # never regress a status the affiliate already recorded.
        'status_seq': event.lead_seq,
        'offer_id': lead.offer_id,
    }
    payload_bytes = json.dumps(payload, default=str).encode()
    signature = _sign(delivery.config.secret, payload_bytes)

    delivery.attempts += 1
    attempt = delivery.attempts

    try:
        resp = requests.post(
            delivery.url, data=payload_bytes,
            headers={
                'Content-Type': 'application/json',
                'X-Nexora-Event': f'lead.status.{event.to_status}',
                'X-Nexora-Delivery': str(delivery.pk),
                'X-Nexora-Signature': signature,
            },
            timeout=10,
        )
        delivery.response_status_code = resp.status_code
        resp.raise_for_status()
        delivery.status = PostbackDelivery.STATUS_DELIVERED
        delivery.delivered_at = timezone.now()
        delivery.last_error = ''
    except Exception as exc:
        delivery.last_error = str(exc)[:500]
        backoffs = PostbackDelivery.RETRY_BACKOFFS
        if attempt < len(backoffs):
            delivery.next_retry_at = timezone.now() + timedelta(seconds=backoffs[attempt - 1])
            delivery.save(update_fields=[
                'attempts', 'last_error', 'next_retry_at', 'response_status_code'])
            raise self.retry(exc=exc, countdown=backoffs[attempt - 1])
        delivery.status = PostbackDelivery.STATUS_FAILED

    delivery.save(update_fields=[
        'attempts', 'status', 'delivered_at', 'last_error', 'next_retry_at', 'response_status_code'])
