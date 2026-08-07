"""Phase 2 of the lead-distribution build (see Nexora_Lead_Distribution_
Build_Guide.md) — walks a lead's resolved buyer chain
(leadgen.routing.resolve_buyer_chain), advancing to the next untried
buyer the moment the current one reaches a TERMINAL outcome (a buyer-side
rejection: duplicate, invalid geo, cap hit — any response where the buyer
validated the lead and said a definite no) or has exhausted its own
transient-failure retries (timeout, 5xx, connection error — the existing
backoff already in tasks.inject_lead_task). A TRANSIENT failure that's
still within its retry budget never advances the chain: the existing
per-buyer Celery retry keeps hammering the SAME buyer exactly as it
already did before this module existed — a hiccup on buyer A must never
dump the lead on buyer B.

This module never touches inject_lead_task's own delivery/retry
mechanics — it reuses them unchanged. tasks.py calls into advance_chain
at each of its terminal points (see the `chain_managed` checks there),
which is the "extend, don't rewrite" the build guide asks for: the core
per-buyer HTTP/retry logic is exactly what it always was; the only
addition is a few lines deciding what happens to the LEAD once a given
buyer attempt is truly finished.

Nothing calls advance_chain automatically from any live capture/intake
path — matching the build guide's explicit non-goal ("auto-routing
enabled by default" is out of scope this pass). It's a complete, tested
capability meant to be triggered deliberately once Paul decides routing
should go live (a later phase's console "Route now" action, a management
command, or direct use).
"""
from .models import Lead, LeadInjection


def _next_untried_buyer(lead, chain):
    """The first buyer in `chain` this lead has no LeadInjection against
    yet. Pure, no side effects. None if every buyer in the chain has
    already been attempted — advance_chain only ever creates one
    LeadInjection per (lead, buyer) pair, so "has an injection already"
    reliably means "already attempted", regardless of how that attempt
    ended (accepted, terminally rejected, or gave up after transient
    retries)."""
    tried_buyer_ids = set(
        LeadInjection.objects.filter(lead=lead, buyer__in=chain).values_list('buyer_id', flat=True)
    )
    for buyer in chain:
        if buyer.pk not in tried_buyer_ids:
            return buyer
    return None


def has_untried_buyer(lead) -> bool:
    """Is there another buyer in this lead's chain that has not been tried?

    Read-only twin of the lookup advance_chain() does — asks "would advancing
    actually go somewhere?" WITHOUT advancing. tasks.inject_lead_task needs
    that question answered before it decides how to handle a capacity refusal
    (connectors.LeadBuyerCapacityError): with a buyer left to try, cascading
    now beats waiting hours on a closed hub, because time-to-contact is what
    decides whether a lead converts. With nowhere to go, waiting is the only
    thing standing between the lead and the bin.

    Deliberately re-derives the chain rather than caching it — same reasoning
    as advance_chain: the chain is a function of current routing config, and
    a stale cursor is how a lead gets skipped or double-sent.
    """
    from .routing import resolve_buyer_chain

    chain = resolve_buyer_chain(lead)
    return bool(chain) and _next_untried_buyer(lead, chain) is not None


def advance_chain(lead_id):
    """Given a lead, either start the next untried buyer in its resolved
    chain, or settle it into a final state:

      - already accepted somewhere (STATUS_INJECTED / STATUS_DEPOSIT) ->
        no-op. This IS the idempotency guard the build guide asks for
        (2.4): safe to call this function any number of times for the
        same lead, from anywhere (a retried Celery task, a double
        trigger), without ever re-entering the chain or double-sending to
        a buyer that already accepted it.
      - the chain resolves empty, or every buyer in it has already been
        tried with no acceptance -> STATUS_UNROUTED. Covers both "never
        had anywhere to send it" and "tried everywhere, nobody wants it"
        — the build guide treats both as the same terminal "exhausted"
        state.
      - otherwise -> start_injection() (async, chain_managed=True) on the
        next untried buyer.

    Always re-derives "what's next" from the actual LeadInjection rows
    rather than tracking a separate progress cursor on Lead, so calling
    this twice in a row can never skip ahead or double-send."""
    from .routing import resolve_buyer_chain
    from .services import start_injection

    try:
        lead = Lead.objects.get(pk=lead_id)
    except Lead.DoesNotExist:
        return

    if lead.status in (Lead.STATUS_INJECTED, Lead.STATUS_DEPOSIT):
        return

    chain = resolve_buyer_chain(lead)
    next_buyer = _next_untried_buyer(lead, chain) if chain else None

    if next_buyer is None:
        Lead.objects.filter(pk=lead.pk).exclude(
            status__in=(Lead.STATUS_INJECTED, Lead.STATUS_DEPOSIT),
        ).touch(status=Lead.STATUS_UNROUTED)
        return

    start_injection(lead, next_buyer, synchronous=False, chain_managed=True)
