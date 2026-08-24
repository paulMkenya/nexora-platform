"""The two-phase status authority engine — Affiliate Inbound API spec §2.
This is the ONLY code allowed to write Lead.canonical_status; every caller
(the buyer-status sync task, and later the operator UI / inbound API) goes
through apply_status_change() so the TESTING/LIVE boundary is enforced in
exactly one place.

The rule (spec §2.2):
  TESTING — operator flips ARE the source of truth. A buyer-sourced status
    change is still recorded (audit trail, spec §3.3) but does NOT touch
    Lead.canonical_status.
  LIVE — the buyer's postback/sync IS the source of truth. An operator flip
    is rejected unless it carries an explicit override_reason (then it's
    allowed, and the reason is logged on the event).

A lead with no affiliate (landing-page traffic, no Nexora affiliate in the
loop) has no AffiliateOfferLink to gate against — status changes for it
always apply directly, phase_at_time='' on the event.
"""
from django.utils import timezone

from . import canonical_status
from .models import AffiliateOfferLink, Lead, LeadStatusEvent


class StatusAuthorityError(Exception):
    """Raised when a status change is rejected by the TESTING/LIVE authority
    rule (an operator flip on a LIVE lead with no override_reason)."""


def resolve_affiliate_offer_link(lead):
    """The AffiliateOfferLink governing this lead, or None if the lead has
    no affiliate (no Nexora affiliate in the loop — nothing to gate).
    get_or_create's default phase is always PHASE_TESTING (models.py's
    AffiliateOfferLink docstring: "a new integration is NEVER born live") —
    the first status change ever attempted for a (affiliate, offer) pair is
    what brings the row into existence."""
    if not lead.affiliate_id or not lead.offer_id:
        return None
    link, _created = AffiliateOfferLink.objects.get_or_create(
        affiliate_id=lead.affiliate_id, offer_id=lead.offer_id)
    return link


def _mapping_key(value):
    """Case- and spacing-insensitive form of a buyer status string.

    Broker free text is not typed consistently — one live box has produced
    both 'No answer' and 'NoAnswer' for a single disposition, in a five-row
    sample. Keying on a folded form means an operator writes the entry once
    instead of chasing every spelling a call centre agent might use, and a
    lead does not silently go to needs_review over a capital letter.
    """
    return ''.join((value or '').split()).casefold()


def map_buyer_status(buyer, raw_status):
    """(canonical_status_or_None, needs_review) for one buyer status string.
    None + needs_review=True when the buyer's status_mapping (see
    LeadBuyer.get_effective_status_mapping) has no entry for raw_status —
    spec §3.2: "do NOT silently drop or guess." A blank raw_status maps to
    nothing and is not itself a review-worthy case (the buyer just hasn't
    reported a status yet).

    EXACT MATCH IS TRIED FIRST and is unchanged, so every mapping that
    resolves today resolves identically and to the same value. Only a string
    that would otherwise have become needs_review gets the second, folded
    lookup — this can turn an unmapped status into a mapped one, never one
    mapped value into a different one.
    """
    if not raw_status:
        return None, False
    mapping = buyer.get_effective_status_mapping()
    mapped = mapping.get(raw_status)
    if mapped is None:
        # Folded fallback. Built per call rather than cached on the buyer:
        # this runs once per changed lead per 30-minute tick, and a cache
        # keyed on a mutable JSONField is a staleness bug waiting to happen.
        folded = {_mapping_key(k): v for k, v in mapping.items()}
        mapped = folded.get(_mapping_key(raw_status))
    if mapped is None:
        return None, True
    return mapped, False


def _is_redundant_buyer_report(lead, to_status, *, current, applies):
    """True when this buyer report would change nothing and tell nobody
    anything new, so it should not be written at all.

    sync_buyer_statuses re-pulls every delivered lead on every Beat tick (every
    30 minutes), and a lead sits at one buyer status for days. Without this
    check each tick wrote a fresh LeadStatusEvent and — for an applied event —
    fired an affiliate postback: a single live lead produced 48 identical
    "pending -> pending" events and 48 postbacks a day, growing linearly with
    lead volume, with nothing downstream able to tell them from a real move.

    The test differs by phase, and getting that wrong strands leads:

    * An APPLYING report (LIVE, or a lead with no affiliate link) is redundant
      only when canonical_status is ALREADY this status. Judging it against the
      buyer's previous word instead would suppress the first authoritative
      report after go-live whenever the buyer had already said the same thing
      during TESTING — the lead would sit at its stale operator-set status
      until the buyer happened to change its mind.
    * A NON-APPLYING report (TESTING-phase buyer) never touches
      canonical_status, so `current` stays different forever and would never
      settle. It is redundant once the buyer's own last word was already this
      status — a pure audit duplicate.
    """
    if applies:
        return current == to_status
    last_buyer_status = (
        LeadStatusEvent.objects
        .filter(lead=lead, source=LeadStatusEvent.SOURCE_BUYER)
        .order_by('-lead_seq')
        .values_list('to_status', flat=True)
        .first()
    )
    return last_buyer_status == to_status


def apply_status_change(lead, to_status, *, source, actor=None, raw_payload=None, override_reason=''):
    """Record a LeadStatusEvent and, if the TESTING/LIVE authority rule
    allows it, update Lead.canonical_status to match. Returns the
    LeadStatusEvent it wrote (check event.applied to see whether it took
    effect), or None when the call was a no-op repeat of the buyer's own
    previous report (see _is_repeat_buyer_report). Raises
    StatusAuthorityError instead of writing anything when a LIVE-phase
    operator flip has no override_reason.

    `lead` may be passed with a possibly-stale canonical_status in memory —
    this function re-reads it from the DB immediately before writing, so two
    concurrent callers can't both compute the same stale from_status (each
    event's from_status reflects the row as it actually was an instant
    before this event, not before the caller's own earlier read)."""
    if to_status not in canonical_status.VALUES:
        raise ValueError(f'Unknown canonical status: {to_status!r}')

    link = resolve_affiliate_offer_link(lead)
    phase = link.phase if link else ''

    if source == LeadStatusEvent.SOURCE_OPERATOR and phase == AffiliateOfferLink.PHASE_LIVE and not override_reason:
        raise StatusAuthorityError(
            f'Lead #{lead.pk} is LIVE — operator flips are locked; pass override_reason to force one.')

    current = Lead.objects.only('canonical_status').get(pk=lead.pk).canonical_status
    applies = not (source == LeadStatusEvent.SOURCE_BUYER and phase == AffiliateOfferLink.PHASE_TESTING)

    # A buyer repeating itself is not news: no event, no postback, no write.
    # Only the buyer is deduplicated — an operator re-affirming a status is a
    # deliberate, audited act and is always recorded. Placed after the
    # authority check so an operator flip is validated identically either way.
    if source == LeadStatusEvent.SOURCE_BUYER and _is_redundant_buyer_report(
        lead, to_status, current=current, applies=applies,
    ):
        return None

    next_seq = LeadStatusEvent.objects.filter(lead=lead).count() + 1

    event = LeadStatusEvent.objects.create(
        lead=lead, from_status=current, to_status=to_status, source=source, actor=actor,
        raw_payload=raw_payload or {}, phase_at_time=phase, applied=applies,
        override_reason=override_reason, lead_seq=next_seq,
    )

    if applies:
        Lead.objects.filter(pk=lead.pk).touch(canonical_status=to_status)
        lead.canonical_status = to_status
        # Return path §5.1 — only an event that actually CHANGED the
        # affiliate-visible status should ever reach the affiliate's postback
        # URL. Two things have to be true for that: the event applied (a
        # recorded-but-not-applied TESTING-phase buyer status stays silent from
        # the affiliate's point of view), and the status it applied differs
        # from what the affiliate was already told. Gating on `applies` alone
        # let a re-affirmation of the current status fire a postback that
        # carried no new information.
        if current != to_status:
            from .postback_delivery import dispatch_postbacks_for_event
            dispatch_postbacks_for_event(event)

    return event


def go_live(link, *, actor):
    """Deliberate, audited testing -> live transition (spec §2.1). One-way
    by default — see revert_to_testing for the (also audited) reverse."""
    link.phase = AffiliateOfferLink.PHASE_LIVE
    link.phase_changed_at = timezone.now()
    link.phase_changed_by = actor
    link.save(update_fields=['phase', 'phase_changed_at', 'phase_changed_by', 'updated_at'])
    return link


def revert_to_testing(link, *, actor):
    """For when a source breaks and needs re-testing (spec §2.1) — an
    operator action too, logged the same way as go_live."""
    link.phase = AffiliateOfferLink.PHASE_TESTING
    link.phase_changed_at = timezone.now()
    link.phase_changed_by = actor
    link.save(update_fields=['phase', 'phase_changed_at', 'phase_changed_by', 'updated_at'])
    return link


def attach_affiliate_phase(leads):
    """Set `.affiliate_phase` on each Lead in `leads` — one extra query
    instead of N, same bulk-attach shape as services.attach_latest_injections
    (My Leads / operator console both list many leads at once). Read-only:
    unlike resolve_affiliate_offer_link, this never get_or_create's a row —
    a pair that's never had a real status change attempted yet is still
    correctly implied TESTING (AffiliateOfferLink's own "never born live"
    default), it just doesn't exist as a row until something writes to it.
    '' for a lead with no affiliate/offer (nothing to phase)."""
    pairs = {(lead.affiliate_id, lead.offer_id) for lead in leads if lead.affiliate_id and lead.offer_id}
    if not pairs:
        for lead in leads:
            lead.affiliate_phase = ''
        return

    affiliate_ids = {p[0] for p in pairs}
    offer_ids = {p[1] for p in pairs}
    phase_by_pair = {
        (link.affiliate_id, link.offer_id): link.phase
        for link in AffiliateOfferLink.objects.filter(affiliate_id__in=affiliate_ids, offer_id__in=offer_ids)
    }
    for lead in leads:
        if lead.affiliate_id and lead.offer_id:
            lead.affiliate_phase = phase_by_pair.get(
                (lead.affiliate_id, lead.offer_id), AffiliateOfferLink.PHASE_TESTING)
        else:
            lead.affiliate_phase = ''
