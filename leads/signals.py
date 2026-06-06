"""Wire Lead tracking onto existing platform events.

Single, defensive path — every handler swallows + logs its own errors so a
tracking hiccup can never break registration, approval, click ingestion, or
offer creation.

  * Profile saved      → create/advance the affiliate Lead (NEW/VERIFIED/APPROVED)
  * Advertiser saved   → create/advance the advertiser Lead
  * Click / Conversion → affiliate activity  → ACTIVATED
  * Offer created      → advertiser activity  → ACTIVATED
"""
import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

from leads import services

logger = logging.getLogger(__name__)


def _safe(fn, *args):
    try:
        fn(*args)
    except Exception:  # noqa: BLE001 — tracking must never break the core flow
        logger.warning('Lead tracking failed in %s', getattr(fn, '__name__', fn),
                       exc_info=True)


@receiver(post_save, sender='user_profile.Profile', dispatch_uid='leads_profile')
def on_profile_saved(sender, instance, **kwargs):
    from user_profile.models import Profile
    if instance.role == Profile.Role.AFFILIATE:
        _safe(services.sync_from_profile, instance)


@receiver(post_save, sender='offer.Advertiser', dispatch_uid='leads_advertiser')
def on_advertiser_saved(sender, instance, **kwargs):
    _safe(services.sync_from_advertiser, instance)


@receiver(post_save, sender='tracker.Click', dispatch_uid='leads_click')
def on_click_saved(sender, instance, created, **kwargs):
    if created:
        _safe(services.record_affiliate_activity, instance.affiliate_id)


@receiver(post_save, sender='tracker.Conversion', dispatch_uid='leads_conversion')
def on_conversion_saved(sender, instance, created, **kwargs):
    if created:
        _safe(services.record_affiliate_activity, instance.affiliate_id)


@receiver(post_save, sender='offer.Offer', dispatch_uid='leads_offer')
def on_offer_saved(sender, instance, created, **kwargs):
    if created and instance.advertiser_id:
        _safe(services.record_advertiser_activity, instance.advertiser_id)
