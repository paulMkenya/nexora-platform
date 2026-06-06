"""Server-side audit trail for "Log in as" / impersonation.

Every impersonation START writes one row (``ended_at`` null); the matching STOP
stamps ``ended_at``. The row is the single source of truth for "who impersonated
whom, in which brand, from which IP, and for how long" — viewable by the platform
owner (all brands) and a brand admin (their own brand only).

The log is *append-on-start, close-on-stop*; it is never deleted by the feature.
"""
from django.conf import settings
from django.db import models


class ImpersonationLog(models.Model):
    impersonator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='impersonations_started',
    )
    target = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='impersonations_received',
    )
    # The target's brand at the time of impersonation (for brand-admin scoping of
    # the audit view). Null only for brandless targets (superuser-reachable).
    brand = models.ForeignKey(
        'brands.Brand',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='impersonation_logs',
    )
    started_at = models.DateTimeField(auto_now_add=True, db_index=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    impersonator_ip = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        ordering = ['-started_at']
        indexes = [
            models.Index(fields=['impersonator', 'target', 'ended_at']),
        ]

    def __str__(self):
        imp = self.impersonator_id or '?'
        tgt = self.target_id or '?'
        return f'impersonation {imp}->{tgt} @ {self.started_at:%Y-%m-%d %H:%M}'

    @property
    def is_active(self):
        return self.ended_at is None
