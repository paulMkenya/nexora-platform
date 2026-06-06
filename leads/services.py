"""Lead lifecycle: create + forward-only stage advancement.

This is the single path for keeping a Lead in sync with its originating entity.
It is called from ``leads.signals`` (off the existing Profile / Advertiser /
Click / Conversion / Offer save events), from the backfill migration, and from
the dormancy beat task. There is no parallel write path.

Stage rules (forward-only auto, manual override is separate, done in the UI):
  * NEW        — on registration (the entity exists).
  * VERIFIED   — when the entity's ``email_verified`` flips True.
  * APPROVED   — when a brand admin approves the entity.
  * ACTIVATED  — on first activity (affiliate: click/conversion; advertiser:
                 first created offer). Also reactivates a DORMANT lead.
  * DORMANT    — set only by the dormancy beat task after N idle days.
"""
import logging

from django.utils import timezone

from leads.models import Lead

logger = logging.getLogger(__name__)

# Forward-only ranking for the auto-progress stages. DORMANT is intentionally
# excluded — it is set only by the beat task and is cleared by new activity.
_PROGRESS_ORDER = {
    Lead.Stage.NEW: 0,
    Lead.Stage.VERIFIED: 1,
    Lead.Stage.APPROVED: 2,
    Lead.Stage.ACTIVATED: 3,
}


def _advance(lead, target, *, extra_fields=None):
    """Move ``lead`` forward to ``target`` if that is ahead of its current
    stage. Never moves a lead backwards and never sets DORMANT here.

    Returns True if the stage changed.
    """
    extra_fields = extra_fields or []
    target_rank = _PROGRESS_ORDER.get(target)
    if target_rank is None:
        return False
    current_rank = _PROGRESS_ORDER.get(lead.pipeline_stage)
    # current_rank is None only for DORMANT; auto-progress never resurrects a
    # dormant lead (activity does that, via record_activity()).
    if current_rank is None or target_rank <= current_rank:
        if extra_fields:
            lead.save(update_fields=extra_fields)
        return False
    lead.pipeline_stage = target
    lead.save(update_fields=['pipeline_stage', *extra_fields])
    return True


def _progress_stage_for_profile(profile):
    # Triggers are independent platform events (approval / verification); the
    # higher pipeline stage wins under forward-only advancement. Approval is an
    # explicit admin action and advances to APPROVED even if verification lags.
    if profile.affiliate_status == profile.AffiliateStatus.APPROVED:
        return Lead.Stage.APPROVED
    if profile.email_verified:
        return Lead.Stage.VERIFIED
    return Lead.Stage.NEW


def _progress_stage_for_advertiser(adv):
    if adv.advertiser_status == adv.AdvertiserStatus.APPROVED:
        return Lead.Stage.APPROVED
    if adv.email_verified:
        return Lead.Stage.VERIFIED
    return Lead.Stage.NEW


def _full_name(*parts):
    return ' '.join(p for p in parts if p).strip()


def sync_from_profile(profile):
    """Create (idempotent) and forward-advance the affiliate's Lead."""
    user = getattr(profile, 'user', None)
    lead, _ = Lead.objects.get_or_create(
        profile=profile,
        defaults={
            'lead_type': Lead.Type.AFFILIATE,
            'brand': profile.brand,
            'email': (user.email if user else '') or '',
            'name': _full_name(getattr(user, 'first_name', ''), getattr(user, 'last_name', ''))
                    or (user.username if user else ''),
            'country': profile.country or '',
        },
    )
    # Keep the denormalised snapshot fresh; brand is stamped once and kept.
    changed = []
    if user and lead.email != (user.email or ''):
        lead.email = user.email or ''
        changed.append('email')
    name = _full_name(getattr(user, 'first_name', ''), getattr(user, 'last_name', '')) \
        or (user.username if user else '')
    if name and lead.name != name:
        lead.name = name
        changed.append('name')
    if profile.country and lead.country != profile.country:
        lead.country = profile.country
        changed.append('country')
    if lead.brand_id is None and profile.brand_id:
        lead.brand = profile.brand
        changed.append('brand')
    _advance(lead, _progress_stage_for_profile(profile), extra_fields=changed)
    return lead


def sync_from_advertiser(adv):
    """Create (idempotent) and forward-advance the advertiser's Lead."""
    user = getattr(adv, 'user', None)
    name = (getattr(user, 'first_name', '') if user else '') or adv.contact_person or adv.company
    email = adv.email or (user.email if user else '') or ''
    lead, _ = Lead.objects.get_or_create(
        advertiser=adv,
        defaults={
            'lead_type': Lead.Type.ADVERTISER,
            'brand': adv.brand,
            'email': email,
            'name': name,
            'country': adv.country or '',
        },
    )
    changed = []
    if email and lead.email != email:
        lead.email = email
        changed.append('email')
    if name and lead.name != name:
        lead.name = name
        changed.append('name')
    if adv.country and lead.country != adv.country:
        lead.country = adv.country
        changed.append('country')
    if lead.brand_id is None and adv.brand_id:
        lead.brand = adv.brand
        changed.append('brand')
    _advance(lead, _progress_stage_for_advertiser(adv), extra_fields=changed)
    return lead


def _record_activity(lead):
    now = timezone.now()
    lead.last_activity_at = now
    fields = ['last_activity_at']
    # Activity activates the lead (and reactivates a dormant one) — the one
    # transition allowed to move a DORMANT lead forward again.
    if lead.pipeline_stage != Lead.Stage.ACTIVATED:
        lead.pipeline_stage = Lead.Stage.ACTIVATED
        fields.append('pipeline_stage')
    lead.save(update_fields=fields)


def record_affiliate_activity(user_id):
    """First/any affiliate activity (click or conversion) → ACTIVATED."""
    if not user_id:
        return
    lead = Lead.objects.filter(profile__user_id=user_id).first()
    if lead is not None:
        _record_activity(lead)


def record_advertiser_activity(advertiser_id):
    """First/any advertiser activity (created offer) → ACTIVATED."""
    if not advertiser_id:
        return
    lead = Lead.objects.filter(advertiser_id=advertiser_id).first()
    if lead is not None:
        _record_activity(lead)


def mark_dormant(days):
    """Flag ACTIVATED leads with no activity for ``days`` days as DORMANT.

    Returns the number of leads updated. Called by the Celery beat task.
    """
    cutoff = timezone.now() - timezone.timedelta(days=days)
    return Lead.objects.filter(
        pipeline_stage=Lead.Stage.ACTIVATED,
        last_activity_at__lt=cutoff,
    ).update(pipeline_stage=Lead.Stage.DORMANT)
