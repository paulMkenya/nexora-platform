"""Outbound lead-injection Celery tasks.

inject_lead_task mirrors public_api.tasks.deliver_webhook closely: same
retry/backoff shape (LeadInjection.RETRY_BACKOFFS = 60s -> 300s -> 1800s,
3 attempts total), same "resolve the row, do the work, save the outcome,
never leave a request/response cycle waiting on a third party" structure.

sync_buyer_statuses is a periodic (Celery Beat) task, not an on-create one:
it pulls whatever CRM/call-center status the buyer tracks for every lead
we've delivered to them (their own free-text status — "New", "Deposit",
"Did not pick call", "Asked for followup", ... — see leadgen.models.Lead.
buyer_status) and keeps our copy in sync.
"""
import logging
from datetime import timedelta

from django.utils import timezone
from django.utils.dateparse import parse_datetime

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


def _parse_buyer_timestamp(raw):
    if not raw:
        return None
    try:
        return parse_datetime(raw)
    except (ValueError, TypeError):
        return None


def sync_buyer_statuses_for_buyer(buyer, *, chunk_size=200):
    """Pull the buyer's own status for every lead successfully delivered to
    them, in chunks of `chunk_size` external IDs per request (op-brandy caps
    PageSize at 200). Updates LeadInjection.buyer_status (source of truth)
    and denormalizes onto Lead.buyer_status; flips Lead.status to
    STATUS_DEPOSIT the moment the buyer reports deposit=True, same as a
    successful injection would. Returns the number of leads updated."""
    from .connectors import LeadBuyerConnector, LeadBuyerError
    from .models import Lead, LeadInjection

    connector = LeadBuyerConnector(buyer)
    injections = list(
        LeadInjection.objects.filter(buyer=buyer, status=LeadInjection.STATUS_DELIVERED)
        .exclude(external_id='')
    )
    if not injections:
        return 0

    by_external_id = {inj.external_id: inj for inj in injections}
    updated = 0

    for i in range(0, len(injections), chunk_size):
        chunk_ids = [inj.external_id for inj in injections[i:i + chunk_size]]
        try:
            response = connector.fetch_lead_statuses(chunk_ids)
        except LeadBuyerError:
            logger.exception(
                'sync_buyer_statuses: fetch failed for buyer %s (chunk of %s)', buyer.slug, len(chunk_ids))
            continue

        for result in connector.parse_status_sync_results(response):
            injection = by_external_id.get(result['external_id'])
            if injection is None:
                continue

            updated_at = _parse_buyer_timestamp(result['updated_at'])
            injection.buyer_status = result['buyer_status']
            injection.buyer_status_updated_at = updated_at
            injection.save(update_fields=['buyer_status', 'buyer_status_updated_at'])

            lead_updates = {'buyer_status': result['buyer_status'], 'buyer_status_updated_at': updated_at}
            if result['deposit']:
                lead_updates['deposit'] = True
                lead_updates['status'] = Lead.STATUS_DEPOSIT
            Lead.objects.filter(pk=injection.lead_id).update(**lead_updates)
            updated += 1

    return updated


@_celery.task(ignore_result=True)
def sync_buyer_statuses():
    """Periodic (Celery Beat) entrypoint — see sync_buyer_statuses_for_buyer.
    One buyer failing (rate-limited, briefly down, etc.) never blocks the
    others."""
    from .models import LeadBuyer

    for buyer in LeadBuyer.objects.filter(is_active=True):
        try:
            count = sync_buyer_statuses_for_buyer(buyer)
            if count:
                logger.info('sync_buyer_statuses: updated %s lead(s) for buyer %s', count, buyer.slug)
        except Exception:
            logger.exception('sync_buyer_statuses failed for buyer %s', buyer.slug)
