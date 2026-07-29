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


def map_buyer_status(buyer, raw_status):
    """(canonical_status_or_None, needs_review) for one buyer status string.
    None + needs_review=True when the buyer's status_mapping (see
    LeadBuyer.get_effective_status_mapping) has no entry for raw_status —
    spec §3.2: "do NOT silently drop or guess." A blank raw_status maps to
    nothing and is not itself a review-worthy case (the buyer just hasn't
    reported a status yet)."""
    if not raw_status:
        return None, False
    mapped = buyer.get_effective_status_mapping().get(raw_status)
    if mapped is None:
        return None, True
    return mapped, False


def apply_status_change(lead, to_status, *, source, actor=None, raw_payload=None, override_reason=''):
    """Record a LeadStatusEvent and, if the TESTING/LIVE authority rule
    allows it, update Lead.canonical_status to match. Always returns the
    LeadStatusEvent it wrote (check event.applied to see whether it took
    effect). Raises StatusAuthorityError instead of writing anything when a
    LIVE-phase operator flip has no override_reason.

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
    next_seq = LeadStatusEvent.objects.filter(lead=lead).count() + 1

    event = LeadStatusEvent.objects.create(
        lead=lead, from_status=current, to_status=to_status, source=source, actor=actor,
        raw_payload=raw_payload or {}, phase_at_time=phase, applied=applies,
        override_reason=override_reason, lead_seq=next_seq,
    )

    if applies:
        Lead.objects.filter(pk=lead.pk).update(canonical_status=to_status)
        lead.canonical_status = to_status
        # Return path §5.1 — only an event that actually changed the
        # affiliate-visible status should ever reach the affiliate's
        # postback URL. A recorded-but-not-applied TESTING-phase buyer
        # status must stay silent from the affiliate's point of view.
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
