"""Outbound lead-injection Celery tasks.

inject_lead_task mirrors public_api.tasks.deliver_webhook closely: same
retry/backoff shape (LeadInjection.RETRY_BACKOFFS = 60s -> 300s -> 1800s,
3 attempts total), same "resolve the row, do the work, save the outcome,
never leave a request/response cycle waiting on a third party" structure.

sync_buyer_statuses is a periodic (Celery Beat) task, not an on-create one:
it pulls whatever CRM/call-center status the buyer tracks for every lead
we've delivered to them (their own free-text status — "New", "Deposit",
"Did not pick call", "Asked for followup", ... — see leadgen.models.Lead.
buyer_status) and keeps our copy in sync. It also backfills
Lead.country_iso2 as a free byproduct, for any lead geolocate_lead didn't
already resolve.

geolocate_lead is a best-effort, on-create IP -> country_iso2 lookup — see
its own docstring for why it never retries or blocks capture.

inject_lead_task also carries the Phase 2 failover hook: on any TERMINAL
outcome (buyer-side rejection, or transient retries exhausted) for an
injection created by leadgen.failover.advance_chain (injection.
chain_managed=True), it calls back into advance_chain to try the next
buyer in the lead's resolved chain. A deliberate single-buyer injection
(chain_managed=False — every UI action, auto-inject, the management
command) never triggers this; the core per-buyer delivery/retry mechanics
below are otherwise exactly what they were before Phase 2 existed.
"""
import logging
from datetime import timedelta

from django.utils import timezone
from django.utils.dateparse import parse_datetime

from project._celery import _celery

logger = logging.getLogger(__name__)


def resolve_buyer_for_lead(lead):
    """The LeadBuyer a lead should be injected to: an active buyer belonging
    to the lead's OWN brand, or None.

    There is no platform-wide fallback any more (Paul's ruling, 2026-08-05):
    a buyer belongs to exactly one brand, and a lead must never leave its
    brand's boundary. A lead whose brand has no active buyer — or a lead with
    no brand at all — resolves to None, which callers already treat as "leave
    it pending, no destination yet" rather than an error. That is the correct
    outcome: pending is recoverable, delivering to another brand's buyer is
    not."""
    from .models import LeadBuyer

    if not lead.brand_id:
        return None
    return LeadBuyer.objects.filter(brand_id=lead.brand_id, is_active=True).first()


def maybe_auto_inject(lead):
    """Called right after a Lead is created (from either intake channel).
    Enqueues injection ONLY if a buyer is resolved AND that buyer has
    auto_inject=True — the kill-switch every new buyer starts with off, same
    shape as payouts' CRYPTO_DISPATCH_ENABLED. Returns the LeadInjection (or
    None if nothing was enqueued).

    No resolvable buyer marks the lead UNROUTED rather than leaving it in
    `new`. Previously it returned silently, so a lead whose brand has no active
    buyer sat indefinitely in `new` — indistinguishable from one still waiting
    its turn, absent from the console's unrouted view, and invisible to a
    reconcile poll because nothing moved updated_at. failover.advance_chain
    already marks exactly this condition UNROUTED ("never had anywhere to send
    it"); the two entry points disagreeing was a latent way to lose leads
    quietly. This matches that precedent rather than inventing a state.

    Only leads created AFTER this ships are affected: this runs at intake, and
    nothing re-evaluates an existing lead.
    """
    from .services import start_injection

    buyer = resolve_buyer_for_lead(lead)
    if buyer is None:
        Lead = lead.__class__
        Lead.objects.filter(pk=lead.pk).exclude(
            status__in=(Lead.STATUS_INJECTED, Lead.STATUS_DEPOSIT),
        ).touch(status=Lead.STATUS_UNROUTED)
        return None
    if not buyer.auto_inject:
        # A destination exists, it is just gated off — that is "waiting", not
        # "nowhere to go", so the lead stays in `new`.
        return None

    return start_injection(lead, buyer, synchronous=False)


# Celery's own ceiling on self.retry(). It must clear the LONGEST schedule
# any branch of inject_lead_task can ask for, which is now
# LeadInjection.CAPACITY_RETRY_BACKOFFS (5) rather than RETRY_BACKOFFS (3) —
# below it, Celery raises MaxRetriesExceededError mid-schedule and the lead
# dies at whatever attempt the cap happens to fall on, silently.
#
# Not derived from the model: importing leadgen.models at decoration time
# would import models from a module models imports back. The invariant is
# pinned instead by test_capacity_retries.py::test_max_retries_clears_the_
# longest_schedule, so the two cannot drift apart unnoticed.
#
# Raising it does not lengthen any OTHER branch: each one bounds itself by
# its own backoff list against the persisted injection.attempts, not by this.
_MAX_INJECTION_RETRIES = 5


@_celery.task(bind=True, max_retries=_MAX_INJECTION_RETRIES, ignore_result=True)
def inject_lead_task(self, injection_id: int):
    from .connectors import (
        LeadBuyerAmbiguousError, LeadBuyerCapacityError, LeadBuyerError,
        LeadBuyerRejectedError, get_connector,
    )
    from .models import Lead, LeadInjection

    try:
        injection = LeadInjection.objects.select_related('lead', 'buyer').get(pk=injection_id)
    except LeadInjection.DoesNotExist:
        return

    if injection.status == LeadInjection.STATUS_DELIVERED:
        return

    lead = injection.lead
    buyer = injection.buyer
    connector = get_connector(buyer)

    injection.attempts += 1
    attempt = injection.attempts
    injection.request_payload = connector.build_payload(lead)  # sanitized — no API key

    # Set True on any TERMINAL outcome for THIS buyer (a buyer-side
    # rejection, or its own transient retries exhausted) — see
    # leadgen.failover for what "advance" means. Left False for a
    # successful delivery (the chain, if any, is done) and for a transient
    # failure still within its retry budget (Celery calls this task again
    # for the SAME buyer; must not skip ahead to the next one).
    reached_terminal_outcome = False

    try:
        response = connector.inject_lead(lead)
        # Default-deny filter before this is persisted: response_payload is
        # rendered to affiliates (affiliate_ui/templates/affiliate_ui/leads.html)
        # and operators (templates/admin_shared/dashboard.html), and a raw
        # buyer response can carry credentials — Hypernet returns an autologin
        # redirect URL. See connectors.sanitize_response_for_audit.
        injection.response_payload = connector.sanitize_response_for_audit(response)
        external_id, status, failure_reason = connector.parse_injection_result(response)
        injection.external_id = external_id
        injection.failure_reason = failure_reason

        if status == 'delivered':
            injection.status = LeadInjection.STATUS_DELIVERED
            injection.delivered_at = timezone.now()
            Lead.objects.filter(pk=lead.pk).touch(status=Lead.STATUS_INJECTED)
        elif status == 'duplicate':
            injection.status = LeadInjection.STATUS_DUPLICATE
            Lead.objects.filter(pk=lead.pk).touch(status=Lead.STATUS_DUPLICATE)
            reached_terminal_outcome = True
        else:
            injection.status = LeadInjection.STATUS_FAILED
            Lead.objects.filter(pk=lead.pk).touch(status=Lead.STATUS_REJECTED)
            # A buyer-side validation rejection (bad phone, etc.) is terminal —
            # retrying the exact same payload would fail identically, unlike a
            # transport/5xx error below.
            injection.save(update_fields=[
                'attempts', 'status', 'external_id', 'failure_reason',
                'request_payload', 'response_payload', 'delivered_at',
            ])
            logger.warning('Lead injection #%s rejected by %s: %s', injection.pk, buyer.name, failure_reason)
            if injection.chain_managed:
                from .failover import advance_chain
                advance_chain(lead.pk)
            return

    except LeadBuyerAmbiguousError as exc:
        # MUST precede the LeadBuyerRejectedError and LeadBuyerError handlers
        # below — both are subclasses, so testing a base first would silently
        # collapse every guard back to "retry" (pinned in
        # tests/test_error_classification.py).
        #
        # The buyer MAY have accepted this lead and we cannot tell (read
        # timeout, 500, unparseable 2xx). Retrying risks a duplicate;
        # cascading to the next buyer is a DOUBLE-SELL. Neither is
        # recoverable, so the lead stops here until a human checks the
        # buyer's own system.
        injection.status = LeadInjection.STATUS_FAILED
        injection.failure_reason = str(exc)[:255]
        Lead.objects.filter(pk=lead.pk).touch(status=Lead.STATUS_QUARANTINED)
        injection.save(update_fields=[
            'attempts', 'status', 'external_id', 'failure_reason',
            'request_payload', 'response_payload', 'delivered_at',
        ])
        logger.error(
            'Lead injection #%s to %s QUARANTINED — outcome unknown, not retried or cascaded: %s',
            injection.pk, buyer.name, exc)
        return

    except LeadBuyerCapacityError as exc:
        # They never evaluated the lead — they had nowhere to route it (hub
        # closed, cap filled, desk paused). Temporary by construction, so
        # this is NOT terminal the way a rejection is. See
        # connectors.LeadBuyerCapacityError.
        #
        # Must precede the base `except LeadBuyerError` below (it is a
        # subclass) but is a SIBLING of LeadBuyerRejectedError, so its
        # position relative to that one is free.
        injection.failure_reason = str(exc)[:255]
        backoffs = LeadInjection.CAPACITY_RETRY_BACKOFFS

        # Somewhere else to send it? Then send it there NOW. A closed hub is
        # precisely what a failover chain exists for, and a buyer who would
        # take this lead this minute beats one who might take it in six
        # hours. Waiting is strictly the fallback for a lead with no
        # alternative — which is the ChainPulse case that motivated this.
        if injection.chain_managed:
            from .failover import has_untried_buyer

            if has_untried_buyer(lead):
                injection.status = LeadInjection.STATUS_FAILED
                injection.save(update_fields=[
                    'attempts', 'status', 'external_id', 'failure_reason',
                    'request_payload', 'response_payload', 'delivered_at',
                ])
                logger.warning(
                    'Lead injection #%s: %s has no capacity; cascading to the next buyer: %s',
                    injection.pk, buyer.name, exc)
                from .failover import advance_chain
                advance_chain(lead.pk)
                return

        # `<=`, not the `<` used for RETRY_BACKOFFS below. That comparison
        # never reaches its own last element (attempt 3 of [60, 300, 1800]
        # goes terminal without ever waiting 1800s); this branch is written
        # to actually use all five of its backoffs. Not folded together
        # because fixing the other one silently changes retry behaviour for
        # every buyer on the platform — a separate decision.
        if attempt <= len(backoffs):
            injection.next_retry_at = timezone.now() + timedelta(seconds=backoffs[attempt - 1])
            injection.save(update_fields=[
                'attempts', 'failure_reason', 'request_payload', 'next_retry_at',
            ])
            logger.warning(
                'Lead injection #%s: %s has no capacity; retry %s of %s in %ss: %s',
                injection.pk, buyer.name, attempt, len(backoffs), backoffs[attempt - 1], exc)
            raise self.retry(exc=exc, countdown=backoffs[attempt - 1])

        # Waited it out and it never opened. STATUS_FAILED, not
        # STATUS_REJECTED: nobody ever looked at this lead, and recording a
        # verdict that was never given would misreport the buyer's quality
        # in every report built on rejection counts.
        injection.status = LeadInjection.STATUS_FAILED
        Lead.objects.filter(pk=lead.pk).touch(status=Lead.STATUS_FAILED)
        logger.error(
            'Lead injection #%s to %s gave up after %s capacity retries over ~%sh: %s',
            injection.pk, buyer.name, attempt, round(sum(backoffs) / 3600, 1), exc)
        reached_terminal_outcome = True

    except LeadBuyerRejectedError as exc:
        # They evaluated the payload and refused it. The identical payload
        # will be refused identically in 60 seconds, so the retry budget is
        # pure added latency on the lead's time-to-contact. Terminal for this
        # buyer; cascade immediately if the chain is managing it.
        injection.status = LeadInjection.STATUS_FAILED
        injection.failure_reason = str(exc)[:255]
        Lead.objects.filter(pk=lead.pk).touch(status=Lead.STATUS_REJECTED)
        injection.save(update_fields=[
            'attempts', 'status', 'external_id', 'failure_reason',
            'request_payload', 'response_payload', 'delivered_at',
        ])
        logger.warning('Lead injection #%s rejected by %s (no retry): %s',
                       injection.pk, buyer.name, exc)
        if injection.chain_managed:
            from .failover import advance_chain
            advance_chain(lead.pk)
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
        Lead.objects.filter(pk=lead.pk).touch(status=Lead.STATUS_FAILED)
        logger.error('Lead injection #%s to %s failed after %s attempts: %s',
                     injection.pk, buyer.name, attempt, exc)
        reached_terminal_outcome = True

    injection.save(update_fields=[
        'attempts', 'status', 'external_id', 'failure_reason',
        'request_payload', 'response_payload', 'delivered_at', 'next_retry_at',
    ])

    if reached_terminal_outcome and injection.chain_managed:
        from .failover import advance_chain
        advance_chain(lead.pk)


@_celery.task(ignore_result=True)
def geolocate_lead(lead_id: int):
    """Best-effort IP -> country_iso2 lookup, fired right after intake (see
    api_views._create_lead / public_views.capture_lead). Never retries — a
    missed geolocation isn't worth spamming ipstack over, and
    sync_buyer_statuses (below) gets a second, free chance to backfill it
    from the buyer's own countryIso2 once the lead's delivered. Requires
    settings.IPSTACK_TOKEN; silently no-ops without one, or on any lookup
    failure (bad/private IP, ipstack down, quota exhausted, ...) — this is a
    routing-quality enhancement, never allowed to affect lead capture."""
    from django.conf import settings

    from .models import Lead

    if not settings.IPSTACK_TOKEN:
        return

    try:
        lead = Lead.objects.get(pk=lead_id)
    except Lead.DoesNotExist:
        return
    if lead.country_iso2 or not lead.ip:
        return

    from ext.ipstack.api import API, Err

    try:
        result = API(settings.IPSTACK_TOKEN).lookup(lead.ip)
    except Err:
        return
    except Exception:
        logger.exception('geolocate_lead: unexpected error looking up lead #%s', lead_id)
        return

    code = (result.country_code or '')[:2]
    if code:
        Lead.objects.filter(pk=lead_id, country_iso2='').touch(country_iso2=code)


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
    successful injection would. Returns the number of leads updated.

    Affiliate Inbound API spec §3.2/§2: this is also where a buyer's raw
    status gets normalized (via buyer.get_effective_status_mapping) into
    Nexora's canonical_status and run through the two-phase authority engine
    (leadgen.status_sync.apply_status_change) — reusing this existing
    pull-based sync rather than building a new buyer-facing ingestion path,
    per the spec's own "buyer-side changes beyond adding status mapping" non-
    goal. An unmapped buyer status sets Lead.canonical_status_needs_review
    instead of guessing."""
    from .connectors import LeadBuyerError, get_connector
    from .models import Lead, LeadInjection
    from .status_sync import LeadStatusEvent, apply_status_change, map_buyer_status

    connector = get_connector(buyer)
    if not connector.supports_status_sync:
        # This box has no usable status-pull (Hypernet filters by date window,
        # not by an ID list, so the base class's Ids= call would return an
        # unrelated page). Its connector raises NotImplementedError rather
        # than answer wrongly — skip it here so that does not surface as a
        # traceback on every Celery Beat tick and train people to ignore the
        # log. See connectors.LeadBuyerConnector.supports_status_sync.
        return 0
    injections = list(
        LeadInjection.objects.select_related('lead')
        .filter(buyer=buyer, status=LeadInjection.STATUS_DELIVERED)
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
            Lead.objects.filter(pk=injection.lead_id).touch(**lead_updates)

            # Free byproduct of this same call — backfill country_iso2 for
            # any lead geolocate_lead didn't already resolve (no IPSTACK
            # token, private/bad IP, etc). Never overwrites an existing value.
            if result.get('country_iso2'):
                Lead.objects.filter(pk=injection.lead_id, country_iso2='').touch(
                    country_iso2=result['country_iso2'])

            canonical, needs_review = map_buyer_status(buyer, result['buyer_status'])
            if needs_review:
                Lead.objects.filter(pk=injection.lead_id).touch(canonical_status_needs_review=True)
                logger.warning(
                    'sync_buyer_statuses: buyer %s status %r has no status_mapping entry (lead #%s)',
                    buyer.slug, result['buyer_status'], injection.lead_id)
            elif canonical:
                # The flag means "this lead's CURRENT buyer status did not
                # resolve — a human should look". Once it resolves, that is no
                # longer true, so clear it. Setting without ever clearing made
                # the flag one-way: adding the missing status_mapping entry
                # fixed the mapping but left every already-flagged lead sitting
                # in the operator's review queue forever with nothing left to
                # review. A queue that fills with resolved rows stops being
                # worth opening, which costs more than the flag ever bought.
                #
                # Only on a REAL resolution, not on the (None, False) that
                # map_buyer_status returns for a blank status — "the buyer has
                # not reported yet" is no evidence that an earlier unmapped
                # status has been dealt with.
                #
                # Filtered on the flag being set so an ordinary sync does not
                # write to every row it touches.
                Lead.objects.filter(
                    pk=injection.lead_id, canonical_status_needs_review=True,
                ).touch(canonical_status_needs_review=False)
                apply_status_change(
                    injection.lead, canonical, source=LeadStatusEvent.SOURCE_BUYER,
                    raw_payload=result)

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
