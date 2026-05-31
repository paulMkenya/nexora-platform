"""
Signal handlers that fire webhook events.

Events emitted:
  offer.created        — when a new Offer is saved (created=True)
  conversion.approved  — when a Conversion status changes to 'approved'
  payout.paid          — when a PayoutRequest status changes to 'paid'
"""
from django.db.models.signals import post_save
from django.dispatch import receiver


@receiver(post_save, sender='offer.Offer')
def on_offer_saved(sender, instance, created, **kwargs):
    if not created:
        return
    if instance.brand_id is None:
        return
    from public_api.tasks import dispatch_webhook_event
    dispatch_webhook_event(
        brand_id=instance.brand_id,
        event='offer.created',
        payload={
            'id': instance.pk,
            'title': instance.title,
            'status': instance.status,
        },
    )


@receiver(post_save, sender='tracker.Conversion')
def on_conversion_saved(sender, instance, created, **kwargs):
    if instance.status != 'approved':
        return
    if created:
        return  # newly created conversions start as rejected/pending, not approved
    if instance.brand_id is None:
        return
    from public_api.tasks import dispatch_webhook_event
    dispatch_webhook_event(
        brand_id=instance.brand_id,
        event='conversion.approved',
        payload={
            'id': str(instance.pk),
            'offer_id': instance.offer_id,
            'revenue': str(instance.revenue),
            'payout': str(instance.payout),
        },
    )


@receiver(post_save, sender='payouts.PayoutRequest')
def on_payout_saved(sender, instance, created, **kwargs):
    if instance.status != 'paid':
        return
    # PayoutRequest doesn't have a brand FK directly; resolve via affiliate profile
    try:
        brand_id = instance.affiliate.profile.brand_id
    except Exception:
        return
    if brand_id is None:
        return
    from public_api.tasks import dispatch_webhook_event
    dispatch_webhook_event(
        brand_id=brand_id,
        event='payout.paid',
        payload={
            'id': instance.pk,
            'amount': str(instance.amount),
            'currency': instance.currency,
        },
    )
