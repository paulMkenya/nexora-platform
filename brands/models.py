import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.db import models

from brands.archival import Archivable


def _fernet():
    """Symmetric cipher for brand secrets, keyed off the Django SECRET_KEY.

    Note: encrypted values are tied to SECRET_KEY; rotating it makes stored SMTP
    passwords undecryptable (they then read as empty and must be re-entered).
    """
    key = base64.urlsafe_b64encode(hashlib.sha256(settings.SECRET_KEY.encode()).digest())
    return Fernet(key)


class Brand(Archivable):
    slug = models.SlugField(max_length=60, unique=True)
    name = models.CharField(max_length=128)
    primary_domain = models.CharField(max_length=253, unique=True)
    tracking_domain = models.CharField(max_length=253, unique=True)
    logo = models.CharField(max_length=500, blank=True, default='')
    favicon = models.CharField(max_length=500, blank=True, default='')
    primary_color = models.CharField(max_length=7, default='#6366f1')
    secondary_color = models.CharField(max_length=7, default='#4f46e5')
    support_email = models.EmailField(max_length=254, default='')
    terms_url = models.CharField(max_length=500, blank=True, default='')
    privacy_url = models.CharField(max_length=500, blank=True, default='')
    is_default = models.BooleanField(default=False)

    # Per-brand outbound email (SMTP). When configured, the brand's
    # transactional mail (password resets, approval/verification notices) is sent
    # through this connection instead of the platform default. The password is
    # stored Fernet-encrypted; never rendered back to the UI.
    smtp_host = models.CharField(max_length=255, blank=True, default='')
    smtp_port = models.PositiveIntegerField(default=587)
    smtp_username = models.CharField(max_length=255, blank=True, default='')
    smtp_password_encrypted = models.CharField(max_length=512, blank=True, default='')
    smtp_use_tls = models.BooleanField(default=True)
    smtp_from_email = models.CharField(max_length=254, blank=True, default='')

    # Where operator notifications for this brand are sent (e.g. a new advertiser
    # registration alert). Configured next to the SMTP settings on the
    # /admin/brands/email-settings/ page. Blank → falls back to a brand admin's
    # own email; if there is none either, the notification is skipped + logged.
    notification_email = models.EmailField(max_length=254, blank=True, default='')

    # Where the PLATFORM OWNER's sales-funnel alerts go (a new public
    # /get-started/ lead). This is the platform's own business data, not a
    # brand's — only the value on the *default* brand is used, and only the
    # superuser edits it (owner-only settings page). UI-configurable so the
    # owner can change where sales alerts land without a redeploy; blank falls
    # back to a sensible default (see ``owner_sales_recipient``).
    owner_sales_notification_email = models.EmailField(
        max_length=254, blank=True, default='')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('name',)

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if self.is_default:
            Brand.objects.exclude(pk=self.pk).filter(is_default=True).update(is_default=False)
        super().save(*args, **kwargs)

    @property
    def is_active(self):
        """An archived brand is disabled — its domains stop serving it."""
        return not self.is_archived

    @classmethod
    def get_default(cls):
        """The fallback brand. Never an archived brand (the default is protected
        from archiving), so active resolution never lands on a disabled brand."""
        return (
            cls.objects.filter(is_default=True, is_archived=False).first()
            or cls.objects.filter(is_archived=False).order_by('id').first()
            or cls.objects.order_by('id').first()
        )

    # --- per-brand SMTP helpers ---

    def set_smtp_password(self, raw):
        """Store (or clear) the SMTP password, encrypted at rest."""
        self.smtp_password_encrypted = _fernet().encrypt(raw.encode()).decode() if raw else ''

    def get_smtp_password(self):
        """Decrypt the stored SMTP password ('' if unset or undecryptable)."""
        if not self.smtp_password_encrypted:
            return ''
        try:
            return _fernet().decrypt(self.smtp_password_encrypted.encode()).decode()
        except (InvalidToken, ValueError):
            return ''

    @property
    def smtp_configured(self):
        """True when this brand has enough to send its own mail."""
        return bool(self.smtp_host and self.smtp_from_email)

    def notification_recipient(self):
        """Where this brand's operator notifications go.

        The configured ``notification_email`` if set; otherwise the email of a
        brand admin (a NETWORK_ADMIN assigned to this brand). Returns '' when
        neither exists — callers skip + log gracefully (never an error).
        """
        if self.notification_email.strip():
            return self.notification_email.strip()
        from user_profile.models import Profile
        admin = (
            Profile.objects.filter(role=Profile.Role.NETWORK_ADMIN, brand=self)
            .exclude(user__email='')
            .select_related('user')
            .order_by('user_id')
            .first()
        )
        return admin.user.email if admin and admin.user else ''

    @classmethod
    def owner_sales_recipient(cls):
        """Where platform-owner sales-funnel alerts are sent.

        The ``owner_sales_notification_email`` configured on the default brand if
        set; otherwise a sensible default — the platform ``ADMIN_EMAIL`` setting,
        else the first superuser's email. Returns '' when nothing is resolvable
        (callers skip + log gracefully, never error).
        """
        from django.conf import settings

        default = cls.get_default()
        if default and default.owner_sales_notification_email.strip():
            return default.owner_sales_notification_email.strip()

        admin_email = getattr(settings, 'ADMIN_EMAIL', '') or ''
        if admin_email.strip():
            return admin_email.strip()

        from django.contrib.auth import get_user_model
        owner = (get_user_model().objects
                 .filter(is_superuser=True).exclude(email='')
                 .order_by('id').first())
        return owner.email if owner else ''
