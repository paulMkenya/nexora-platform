"""Shared injection helpers — the one place every 'send this lead to that
buyer' entry point (auto-inject on capture, the inject_pending_leads
command, and every manual 'inject now' UI surface: Django admin action,
affiliate My Leads page, operator dashboard) does the create-row +
trigger-task mechanics, so that mechanic only exists once."""
from .models import LeadInjection
from .tasks import inject_lead_task


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
    injection = LeadInjection.objects.create(lead=lead, buyer=buyer, chain_managed=chain_managed)
    if synchronous:
        try:
            inject_lead_task(injection.pk)
        except Exception:
            pass  # a scheduled Celery retry raises Retry — state is already saved
        injection.refresh_from_db()
    else:
        inject_lead_task.delay(injection.pk)
    return injection


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
