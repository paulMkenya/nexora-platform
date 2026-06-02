"""Per-brand outbound email.

A brand can configure its own SMTP credentials (see Brand.smtp_*). When set, the
brand's transactional mail is sent through that connection with the brand's
From address; otherwise it falls back to the platform default backend (which is
the console backend until global SMTP is configured in the environment).
"""
from django.conf import settings
from django.core.mail import EmailMessage, get_connection


def connection_for_brand(brand):
    """An SMTP connection from the brand's creds, or the platform default."""
    if brand is not None and getattr(brand, 'smtp_configured', False):
        return get_connection(
            backend='django.core.mail.backends.smtp.EmailBackend',
            host=brand.smtp_host,
            port=brand.smtp_port,
            username=brand.smtp_username,
            password=brand.get_smtp_password(),
            use_tls=brand.smtp_use_tls,
            fail_silently=False,
        )
    return get_connection()


def from_email_for_brand(brand):
    """The brand's From address, or the platform default."""
    if brand is not None and getattr(brand, 'smtp_from_email', ''):
        return brand.smtp_from_email
    return settings.DEFAULT_FROM_EMAIL


def send_brand_mail(brand, subject, body, to, fail_silently=True):
    """Send a plain-text email on behalf of a brand (its SMTP if configured)."""
    msg = EmailMessage(
        subject=subject,
        body=body,
        from_email=from_email_for_brand(brand),
        to=to,
        connection=connection_for_brand(brand),
    )
    return msg.send(fail_silently=fail_silently)
