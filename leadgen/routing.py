"""The routing brain — Phase 1 of the lead-distribution build. Kept in its
own module, separate from tasks.py, because resolve_buyer_chain() is meant
to be exhaustively unit-tested as a pure function: no Celery, no network,
no side effects, just "given this lead and these rules, what's the buyer
chain" — the guide's own words for why this piece gets isolated.

Phase 1 ships the engine + admin (see leadgen/admin.py) to create rules +
this module's tests. Nothing on the delivery path (tasks.py, services.py)
calls resolve_buyer_chain() yet — routing is computed, not wired to
auto-send, until a later phase explicitly enables it. Every RoutingRule
also defaults to is_active=False, so even a saved rule is inert until
someone deliberately flips it on — the same kill-switch posture as
LeadBuyer.auto_inject.
"""
from .models import RoutingRule


def resolve_buyer_chain(lead):
    """The ordered list of active LeadBuyers to attempt for `lead`, per its
    brand's active RoutingRules — no side effects, no network calls, and
    (aside from reading rules from the database) no I/O: same input always
    produces the same output.

    Matching: a rule matches `lead` if every criterion it SETS (offer,
    country_iso2, affiliate, vertical, source_channel) equals the lead's
    corresponding value; a blank/null criterion on the rule is a wildcard
    that matches any lead. A rule with every criterion blank matches every
    lead in its brand.

    Rules are brand-scoped: a lead with no brand attributed never matches
    anything (returns []); a rule never matches a lead in a different
    brand. Only is_active rules and is_active buyers are considered.
    Rules are tried in `priority` order (lower first, then `id` for a
    stable tie-break); if multiple matching rules point at the same buyer,
    that buyer appears once, at its first (highest-priority) position.

    Returns [] — not an error — when nothing matches; callers must treat an
    empty chain as "no destination configured yet", not a failure."""
    if lead.brand_id is None:
        return []

    rules = (
        RoutingRule.objects
        .filter(brand_id=lead.brand_id, is_active=True, buyer__is_active=True)
        .select_related('buyer')
        .order_by('priority', 'id')
    )

    chain = []
    seen_buyer_ids = set()
    for rule in rules:
        if rule.offer_id is not None and rule.offer_id != lead.offer_id:
            continue
        if rule.country_iso2 and rule.country_iso2 != lead.country_iso2:
            continue
        if rule.affiliate_id is not None and rule.affiliate_id != lead.affiliate_id:
            continue
        if rule.vertical and rule.vertical != lead.vertical:
            continue
        if rule.source_channel and rule.source_channel != lead.intake_channel:
            continue

        if rule.buyer_id not in seen_buyer_ids:
            chain.append(rule.buyer)
            seen_buyer_ids.add(rule.buyer_id)

    return chain
