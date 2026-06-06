"""Celery task for the platform sales funnel.

``notify_platform_lead`` emails the PLATFORM OWNER's sales-notification address
when a new public lead arrives on ``/get-started/``. It is dispatched async so a
slow mail server never blocks the public form response, and it is fail-safe: any
problem is logged and swallowed, never raised back into the request. A blank
recipient is a graceful skip (logged), not an error.

The recipient is resolved from ``Brand.owner_sales_recipient()`` (the
owner-configurable address on the default brand, with sensible fallbacks) and
the mail is sent through ``send_brand_mail`` on the default brand so it uses the
platform's own From address / SMTP.
"""
import logging

from django.conf import settings

from brands.email import send_brand_mail
from brands.models import Brand
from project._celery import _celery

logger = logging.getLogger(__name__)


@_celery.task
def notify_platform_lead(lead_id):
    """Email the platform owner about a new sales-funnel lead. Fail-safe."""
    from platform_leads.models import PlatformLead

    lead = (PlatformLead.objects
            .prefetch_related('verticals', 'traffic_sources')
            .filter(pk=lead_id).first())
    if lead is None:
        return 0

    recipient = Brand.owner_sales_recipient()
    if not recipient:
        logger.info(
            'No owner sales-notification recipient configured; skipping '
            'platform-lead alert for lead=%s', lead_id)
        return 0

    brand = Brand.get_default()
    host = (brand.primary_domain if brand else '') or getattr(settings, 'PRIMARY_DOMAIN', '')
    link = (f'https://{host}/admin/platform-leads/{lead.pk}/'
            if host else f'/admin/platform-leads/{lead.pk}/')

    verticals = ', '.join(c.name for c in lead.verticals.all()) or '—'
    subject = f'New platform lead ({lead.get_lead_type_display()}): {lead.name}'
    body = (
        'A new prospect submitted the get-started form.\n\n'
        f'Type:      {lead.get_lead_type_display()}\n'
        f'Name:      {lead.name}\n'
        f'Company:   {lead.company or "—"}\n'
        f'Email:     {lead.email}\n'
        f'Phone:     {lead.phone or "—"}\n'
        f'Country:   {lead.country or "—"}\n'
        f'Scale:     {lead.scale or "—"}\n'
        f'Verticals: {verticals}\n'
        f'Timeline:  {lead.get_timeline_display() or "—"}\n'
        f'Pain:      {lead.pain or "—"}\n\n'
        f'Work this lead in the owner pipeline:\n{link}\n'
    )
    # fail_silently default → swallow+log inside send_brand_mail.
    return send_brand_mail(brand, subject, body, [recipient])


def enqueue_platform_lead_alert(lead_id):
    """Dispatch the owner alert async, with an inline fail-safe fallback.

    In production the task runs on the Celery worker. If the broker is briefly
    unreachable we fall back to an inline send so the alert isn't silently lost
    — and even that is wrapped so the public form can never 500.
    """
    try:
        notify_platform_lead.delay(lead_id)
    except Exception:  # noqa: BLE001 — broker down: degrade to inline, never raise
        logger.warning('Celery dispatch failed; sending platform-lead alert inline',
                       exc_info=True)
        try:
            notify_platform_lead(lead_id)
        except Exception:
            logger.warning('Inline platform-lead alert failed', exc_info=True)
