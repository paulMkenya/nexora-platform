"""Per-brand outbound email.

A brand can configure its own SMTP credentials (see Brand.smtp_*). When set, the
brand's transactional mail is sent through that connection with the brand's
From address; otherwise it falls back to the platform default backend (which is
the console backend until global SMTP is configured in the environment).

All sends are fail-safe: a broken SMTP config must never 500 a user-facing
request. ``send_brand_mail`` swallows+logs failures; the password-reset form
wraps its own send the same way. A short connection timeout keeps a dead host
from hanging the request.
"""
import logging
import smtplib
import socket

from django.conf import settings
from django.core.mail import EmailMessage, get_connection

logger = logging.getLogger(__name__)


def _timeout():
    return getattr(settings, 'EMAIL_TIMEOUT', 10)


def connection_for_brand(brand, fail_silently=False):
    """An SMTP connection from the brand's creds, or the platform default.

    A short timeout is always applied so an unreachable host can't hang the
    worker/request thread.
    """
    if brand is not None and getattr(brand, 'smtp_configured', False):
        return get_connection(
            backend='django.core.mail.backends.smtp.EmailBackend',
            host=brand.smtp_host,
            port=brand.smtp_port,
            username=brand.smtp_username,
            password=brand.get_smtp_password(),
            use_tls=brand.smtp_use_tls,
            timeout=_timeout(),
            fail_silently=fail_silently,
        )
    return get_connection(timeout=_timeout(), fail_silently=fail_silently)


def from_email_for_brand(brand):
    """The brand's From address, or the platform default."""
    if brand is not None and getattr(brand, 'smtp_from_email', ''):
        return brand.smtp_from_email
    return settings.DEFAULT_FROM_EMAIL


def send_brand_mail(brand, subject, body, to, fail_silently=True):
    """Send a plain-text email on behalf of a brand (its SMTP if configured).

    Fail-safe by default: a send failure is logged, not raised, so it can never
    500 a user-facing request.
    """
    try:
        msg = EmailMessage(
            subject=subject,
            body=body,
            from_email=from_email_for_brand(brand),
            to=to,
            connection=connection_for_brand(brand, fail_silently=fail_silently),
        )
        return msg.send(fail_silently=fail_silently)
    except Exception:
        logger.warning('Brand email send failed (brand=%s, to=%s)',
                       getattr(brand, 'slug', None), to, exc_info=True)
        if not fail_silently:
            raise
        return 0


def describe_smtp_error(exc) -> str:
    """Map an email-send exception to a specific, operator-actionable reason."""
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return 'Authentication failed — check the SMTP username and password.'
    if isinstance(exc, smtplib.SMTPConnectError):
        return 'Connection refused by the SMTP server — check the host and port.'
    if isinstance(exc, smtplib.SMTPSenderRefused):
        return 'The server rejected the From address — check the From email.'
    if isinstance(exc, socket.gaierror):
        return 'Unknown host — the SMTP host name could not be resolved.'
    if isinstance(exc, (socket.timeout, TimeoutError)):
        return 'Connection timed out — check the host/port and that the server is reachable.'
    if isinstance(exc, ConnectionRefusedError):
        return 'Connection refused — check the host and port.'
    if isinstance(exc, smtplib.SMTPException):
        return f'SMTP error: {exc}'
    if isinstance(exc, OSError):
        return f'Network error: {exc}'
    return f'Send failed: {exc}'


def send_test_email(brand, to_address):
    """Send a test email through the brand's SAVED SMTP. Returns (ok, message).

    Never raises — the failure reason is returned for inline display.
    """
    if not getattr(brand, 'smtp_configured', False):
        return False, 'No custom SMTP is configured for this brand — save an SMTP host and From address first.'
    try:
        EmailMessage(
            subject=f'{brand.name} — SMTP test email',
            body=(
                f'This is a test email from {brand.name}.\n\n'
                'If you received it, your brand SMTP settings are working.'
            ),
            from_email=from_email_for_brand(brand),
            to=[to_address],
            connection=connection_for_brand(brand, fail_silently=False),
        ).send(fail_silently=False)
        return True, f'Test email sent to {to_address}'
    except Exception as exc:  # noqa: BLE001 — surfaced to the operator, also logged
        logger.warning('Brand SMTP test failed (brand=%s): %s', getattr(brand, 'slug', None), exc)
        return False, describe_smtp_error(exc)
