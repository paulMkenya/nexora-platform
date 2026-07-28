"""Shared synchronous-injection helper used by every 'inject now' UI surface
(Django admin action, affiliate My Leads page, operator dashboard) so the
create-injection-row + run-task + collect-result loop lives in one place."""
from .models import LeadInjection
from .tasks import inject_lead_task


def inject_leads_to_buyer(leads, buyer):
    """Synchronously inject each lead in `leads` to `buyer`.

    Returns a list of (lead, injection) tuples in the same order. Runs
    inject_lead_task inline (not queued via .delay()) so callers get an
    immediate delivered/duplicate/failed result — meant for deliberate,
    low-volume manual actions, not bulk automation (that's what
    LeadBuyer.auto_inject + Celery is for)."""
    results = []
    for lead in leads:
        injection = LeadInjection.objects.create(lead=lead, buyer=buyer)
        try:
            inject_lead_task(injection.pk)
        except Exception:
            pass  # a scheduled Celery retry raises Retry — state is already saved
        injection.refresh_from_db()
        results.append((lead, injection))
    return results


def summarize_injection_results(results):
    """(delivered, duplicate, failed) counts from inject_leads_to_buyer's output."""
    delivered = sum(1 for _, inj in results if inj.status == LeadInjection.STATUS_DELIVERED)
    duplicate = sum(1 for _, inj in results if inj.status == LeadInjection.STATUS_DUPLICATE)
    failed = len(results) - delivered - duplicate
    return delivered, duplicate, failed
