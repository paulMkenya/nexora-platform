"""Shared injection helpers — the one place every 'send this lead to that
buyer' entry point (auto-inject on capture, the inject_pending_leads
command, and every manual 'inject now' UI surface: Django admin action,
affiliate My Leads page, operator dashboard) does the create-row +
trigger-task mechanics, so that mechanic only exists once."""
import logging

from .models import LeadInjection
from .tasks import inject_lead_task

logger = logging.getLogger(__name__)


def start_injection(lead, buyer, *, synchronous, chain_managed=False):
    """Create the LeadInjection row and trigger delivery — the one place
    'create a LeadInjection + run inject_lead_task' happens, shared by every
    caller (auto-inject, the management command, every manual UI action).

    synchronous=True runs inject_lead_task inline and returns once the
    outcome (delivered/duplicate/failed) is known — for deliberate,
    low-volume manual actions where a human is waiting on the result.
    synchronous=False queues it via Celery .delay() — for auto-inject and
    bulk/background enqueueing, where nothing should block on a third party.
    Required keyword, no default: every caller must be deliberate about
    which one it wants.

    chain_managed defaults to False for every ordinary caller. Only
    leadgen.failover.advance_chain passes True — see LeadInjection.
    chain_managed's docstring for why this needs to be explicit rather than
    inferred."""
    # Layer 3 of the cross-brand guard, and the last one before the wire.
    # Every path that delivers a lead comes through here, so whatever went
    # wrong upstream — a hand-written rule, a shell, a future caller that
    # forgets — a lead cannot leave its own brand's boundary. Refuse loudly
    # rather than deliver to the wrong counterparty: this is somebody's money.
    if lead.brand_id != buyer.brand_id:
        logger.error(
            'BLOCKED cross-brand injection: lead %s (brand=%s) -> buyer %s (brand=%s)',
            lead.pk, lead.brand_id, buyer.pk, buyer.brand_id,
        )
        raise ValueError(
            f'Cross-brand injection refused: lead {lead.pk} belongs to brand '
            f'{lead.brand_id} but buyer "{buyer.name}" belongs to brand {buyer.brand_id}.'
        )

    injection = LeadInjection.objects.create(lead=lead, buyer=buyer, chain_managed=chain_managed)
    if synchronous:
        try:
            inject_lead_task(injection.pk)
        except Exception:
            # The task asking for a retry raises — Celery re-raises the
            # ORIGINAL exception rather than Retry when the task was called
            # directly (self.request.called_directly). Either way the row is
            # already saved, so there is nothing to do here but look at it.
            pass
        injection.refresh_from_db()
        _hand_pending_retry_to_celery(injection)
    else:
        inject_lead_task.delay(injection.pk)
    return injection


def _hand_pending_retry_to_celery(injection) -> bool:
    """Give a synchronously-attempted injection that asked for a retry an
    actual scheduler. Returns whether one was queued.

    THE BUG THIS EXISTS TO CLOSE: ``next_retry_at`` is a display column.
    Nothing sweeps it — no Beat task, no cron, nothing. The only thing that
    ever re-runs an injection is Celery's own ``self.retry(countdown=...)``,
    and that schedules nothing when the task was called DIRECTLY: Celery sees
    ``called_directly`` and re-raises instead of enqueueing. start_injection's
    synchronous branch calls it directly.

    So before this, a synchronous attempt that ended in "retry later" wrote a
    convincing ``next_retry_at``, returned an injection sitting at PENDING,
    and then nothing ever happened. Forever. Silently — the row looks alive,
    the console shows a scheduled time that passes and never fires.

    That path is every manual "inject now" surface, including the Django
    admin action (leadgen/admin.py inject_to_buyer), which is exactly what an
    operator reaches for when a buyer has been refusing leads. It mattered
    little while the only retryable failures were seconds-long network
    blips; LeadBuyerCapacityError made "retry later" a normal, hours-long
    outcome, and turned a latent hole into the common case.

    PENDING + a retry time is precisely the "I asked for a retry" signal:
    every terminal branch sets a non-PENDING status first. A stale
    ``next_retry_at`` left on a FAILED row (the terminal branches do not
    clear it) therefore cannot trigger this.
    """
    if injection.status != LeadInjection.STATUS_PENDING or not injection.next_retry_at:
        return False

    # eta, not countdown: the task already decided WHEN, and it may have been
    # deciding a while ago if the buyer was slow to answer. A past eta runs
    # immediately, which is the right reading of an overdue retry — and
    # cannot loop, because each run increments the persisted attempt counter.
    inject_lead_task.apply_async((injection.pk,), eta=injection.next_retry_at)
    logger.info(
        'Injection #%s was attempted synchronously and asked to retry at %s; '
        'queued with Celery (nothing else would have run it).',
        injection.pk, injection.next_retry_at)
    return True


def inject_leads_to_buyer(leads, buyer):
    """Synchronously inject each lead in `leads` to `buyer`.

    Returns a list of (lead, injection) tuples in the same order — meant for
    deliberate, low-volume manual actions, not bulk automation (that's what
    LeadBuyer.auto_inject + Celery is for)."""
    return [(lead, start_injection(lead, buyer, synchronous=True)) for lead in leads]


def summarize_injection_results(results):
    """(delivered, duplicate, failed) counts from inject_leads_to_buyer's output."""
    delivered = sum(1 for _, inj in results if inj.status == LeadInjection.STATUS_DELIVERED)
    duplicate = sum(1 for _, inj in results if inj.status == LeadInjection.STATUS_DUPLICATE)
    failed = len(results) - delivered - duplicate
    return delivered, duplicate, failed


def attach_latest_injections(leads):
    """Set `.latest_injection` on each Lead in `leads` (or None) — one extra
    query instead of N, so a leads table can show "why did this fail" (buyer,
    attempts, failure reason, raw response) without leaving the page it's
    rendered on (operator dashboard, affiliate My Leads)."""
    lead_ids = [lead.pk for lead in leads]
    latest_by_lead = {}
    for injection in LeadInjection.objects.filter(lead_id__in=lead_ids).select_related('buyer').order_by('-created_at'):
        latest_by_lead.setdefault(injection.lead_id, injection)
    for lead in leads:
        lead.latest_injection = latest_by_lead.get(lead.pk)
