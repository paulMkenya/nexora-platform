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


def _rule_matches(rule, lead):
    """True if every criterion `rule` SETS (offer, country_iso2, affiliate,
    vertical, source_channel) equals `lead`'s corresponding value; a blank/
    null criterion on the rule is a wildcard that matches any lead. Pure,
    no queries — caller supplies both objects already loaded."""
    if rule.offer_id is not None and rule.offer_id != lead.offer_id:
        return False
    if rule.country_iso2 and rule.country_iso2 != lead.country_iso2:
        return False
    if rule.affiliate_id is not None and rule.affiliate_id != lead.affiliate_id:
        return False
    if rule.vertical and rule.vertical != lead.vertical:
        return False
    if rule.source_channel and rule.source_channel != lead.intake_channel:
        return False
    return True


def _chain_from_rules(lead, rules):
    """Ordered, deduplicated buyer list for `lead` given an already-fetched,
    already-ordered (priority, id) iterable of candidate rules."""
    chain = []
    seen_buyer_ids = set()
    for rule in rules:
        if not _rule_matches(rule, lead):
            continue
        if rule.buyer_id not in seen_buyer_ids:
            chain.append(rule.buyer)
            seen_buyer_ids.add(rule.buyer_id)
    return chain


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
    return _chain_from_rules(lead, rules)


def attach_computed_chains(leads):
    """Set `.computed_chain` (a list of LeadBuyer) on each Lead in `leads`
    — what resolve_buyer_chain(lead) WOULD return, computed in bulk: one
    query for active rules per distinct brand among `leads` (not one query
    per lead), for a leads-console table showing "what routing would do"
    without an N+1. Leads with no brand get an empty list, same as
    resolve_buyer_chain's own behavior."""
    brand_ids = {lead.brand_id for lead in leads if lead.brand_id is not None}
    rules_by_brand = {}
    if brand_ids:
        all_rules = (
            RoutingRule.objects
            .filter(brand_id__in=brand_ids, is_active=True, buyer__is_active=True)
            .select_related('buyer')
            .order_by('priority', 'id')
        )
        for rule in all_rules:
            rules_by_brand.setdefault(rule.brand_id, []).append(rule)

    for lead in leads:
        rules = rules_by_brand.get(lead.brand_id, [])
        lead.computed_chain = _chain_from_rules(lead, rules)
