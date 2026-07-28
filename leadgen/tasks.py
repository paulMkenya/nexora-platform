"""Outbound lead-injection Celery tasks.

inject_lead_task mirrors public_api.tasks.deliver_webhook closely: same
retry/backoff shape (LeadInjection.RETRY_BACKOFFS = 60s -> 300s -> 1800s,
3 attempts total), same "resolve the row, do the work, save the outcome,
never leave a request/response cycle waiting on a third party" structure.
"""
import logging
from datetime import timedelta

from django.utils import timezone

from project._celery import _celery

logger = logging.getLogger(__name__)


def resolve_buyer_for_lead(lead):
    """The LeadBuyer a lead should be injected to: the lead's own brand's
    active buyer first, falling back to the platform-wide buyer (brand=None).
    Returns None if nothing is configured — callers must treat that as "leave
    it pending, no destination yet" rather than an error."""
    from .models import LeadBuyer

    if lead.brand_id:
        buyer = LeadBuyer.objects.filter(brand_id=lead.brand_id, is_active=True).first()
        if buyer:
            return buyer
    return LeadBuyer.objects.filter(brand__isnull=True, is_active=True).first()


def maybe_auto_inject(lead):
    """Called right after a Lead is created (from either intake channel).
    Enqueues injection ONLY if a buyer is resolved AND that buyer has
    auto_inject=True — the kill-switch every new buyer starts with off, same
    shape as payouts' CRYPTO_DISPATCH_ENABLED. Returns the LeadInjection (or
    None if nothing was enqueued)."""
    from .models import LeadInjection

    buyer = resolve_buyer_for_lead(lead)
    if buyer is None or not buyer.auto_inject:
        return None

    injection = LeadInjection.objects.create(lead=lead, buyer=buyer)
    inject_lead_task.delay(injection.pk)
    return injection


@_celery.task(bind=True, max_retries=3, ignore_result=True)
def inject_lead_task(self, injection_id: int):
    from .connectors import LeadBuyerConnector, LeadBuyerError
    from .models import Lead, LeadInjection

    try:
        injection = LeadInjection.objects.select_related('lead', 'buyer').get(pk=injection_id)
    except LeadInjection.DoesNotExist:
        return

    if injection.status == LeadInjection.STATUS_DELIVERED:
        return

    lead = injection.lead
    buyer = injection.buyer
    connector = LeadBuyerConnector(buyer)

    injection.attempts += 1
    attempt = injection.attempts
    injection.request_payload = connector.build_payload(lead)  # sanitized — no API key

    try:
        response = connector.inject_lead(lead)
        injection.response_payload = response
        external_id, status, failure_reason = connector.parse_injection_result(response)
        injection.external_id = external_id
        injection.failure_reason = failure_reason

        if status == 'delivered':
            injection.status = LeadInjection.STATUS_DELIVERED
            injection.delivered_at = timezone.now()
            Lead.objects.filter(pk=lead.pk).update(status=Lead.STATUS_INJECTED)
        elif status == 'duplicate':
            injection.status = LeadInjection.STATUS_DUPLICATE
            Lead.objects.filter(pk=lead.pk).update(status=Lead.STATUS_DUPLICATE)
        else:
            injection.status = LeadInjection.STATUS_FAILED
            Lead.objects.filter(pk=lead.pk).update(status=Lead.STATUS_REJECTED)
            # A buyer-side validation rejection (bad phone, etc.) is terminal —
            # retrying the exact same payload would fail identically, unlike a
            # transport/5xx error below.
            injection.save(update_fields=[
                'attempts', 'status', 'external_id', 'failure_reason',
                'request_payload', 'response_payload', 'delivered_at',
            ])
            logger.warning('Lead injection #%s rejected by %s: %s', injection.pk, buyer.name, failure_reason)
            return

    except LeadBuyerError as exc:
        injection.failure_reason = str(exc)[:255]
        backoffs = LeadInjection.RETRY_BACKOFFS
        if attempt < len(backoffs):
            injection.next_retry_at = timezone.now() + timedelta(seconds=backoffs[attempt - 1])
            injection.save(update_fields=[
                'attempts', 'failure_reason', 'request_payload', 'next_retry_at',
            ])
            raise self.retry(exc=exc, countdown=backoffs[attempt - 1])
        injection.status = LeadInjection.STATUS_FAILED
        Lead.objects.filter(pk=lead.pk).update(status=Lead.STATUS_FAILED)
        logger.error('Lead injection #%s to %s failed after %s attempts: %s',
                     injection.pk, buyer.name, attempt, exc)

    injection.save(update_fields=[
        'attempts', 'status', 'external_id', 'failure_reason',
        'request_payload', 'response_payload', 'delivered_at', 'next_retry_at',
    ])
