"""Celery tasks for the lead pipeline.

  * ``mark_dormant_leads`` — beat task; flags idle ACTIVATED leads as DORMANT.
  * ``notify_advertiser_registration`` — fail-safe async alert to the brand's
    notification email when a new advertiser self-registers.

Both are dispatched async so a slow mail server (or a long scan) never blocks
the registration response, and both are fail-safe: a failure is logged, never
raised back into a user-facing request.
"""
import logging

from django.conf import settings

from brands.email import send_brand_mail
from project._celery import _celery

logger = logging.getLogger(__name__)


@_celery.task
def mark_dormant_leads():
    """Flag ACTIVATED leads idle beyond ``LEADS_DORMANT_DAYS`` as DORMANT."""
    from leads import services
    days = getattr(settings, 'LEADS_DORMANT_DAYS', 30)
    count = services.mark_dormant(days)
    if count:
        logger.info('Marked %s lead(s) dormant (idle > %s days)', count, days)
    return count


@_celery.task
def notify_advertiser_registration(advertiser_id):
    """Email the brand's notification recipient about a new advertiser.

    Fail-safe: any problem is logged and swallowed. A blank recipient is a
    graceful skip (logged), not an error.
    """
    from offer.models import Advertiser

    adv = (Advertiser.objects.select_related('brand', 'user')
           .filter(pk=advertiser_id).first())
    if adv is None:
        return 0

    brand = adv.brand
    recipient = brand.notification_recipient() if brand else ''
    if not recipient:
        logger.info(
            'No notification recipient for brand=%s; skipping advertiser '
            'registration alert for advertiser=%s',
            getattr(brand, 'slug', None), advertiser_id,
        )
        return 0

    brand_name = brand.name if brand else 'Nexora'
    contact = (adv.user.first_name if adv.user else '') or adv.contact_person
    name = adv.company or contact
    email = adv.email or (adv.user.email if adv.user else '')
    country = adv.country or 'unspecified'
    host = (brand.primary_domain if brand else '') or getattr(settings, 'PRIMARY_DOMAIN', '')
    link = f'https://{host}/admin/advertisers/' if host else '/admin/advertisers/'

    subject = f'New advertiser registration: {name}'
    body = (
        f'A new advertiser has registered on {brand_name}.\n\n'
        f'Company: {adv.company}\n'
        f'Contact: {contact or "—"}\n'
        f'Email:   {email}\n'
        f'Brand:   {brand_name}\n'
        f'Country: {country}\n\n'
        f'Review and approve advertisers here:\n{link}\n'
    )
    # fail_silently default → swallow+log inside send_brand_mail.
    return send_brand_mail(brand, subject, body, [recipient])


def enqueue_advertiser_registration_alert(advertiser_id):
    """Dispatch the advertiser alert async, with an inline fail-safe fallback.

    In production the task runs on the Celery worker. If the broker is briefly
    unreachable we fall back to an inline send so the alert isn't silently lost
    — and even that is wrapped so registration can never 500.
    """
    try:
        notify_advertiser_registration.delay(advertiser_id)
    except Exception:  # noqa: BLE001 — broker down: degrade to inline, never raise
        logger.warning('Celery dispatch failed; sending advertiser alert inline',
                       exc_info=True)
        try:
            notify_advertiser_registration(advertiser_id)
        except Exception:
            logger.warning('Inline advertiser alert failed', exc_info=True)
