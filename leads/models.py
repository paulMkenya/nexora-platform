"""Brand-scoped CRM Lead.

A ``Lead`` is the pipeline record for one self-registered entity — either an
affiliate (``user_profile.Profile``) or an advertiser (``offer.Advertiser``).
There is exactly **one** Lead per entity (enforced by the one-to-one links), so
tracking is idempotent: re-running registration / backfill never creates a
duplicate.

The Lead is *brand-scoped*: ``brand`` is stamped at registration from the entity
and is the single key the operator pipeline view filters on (via the shared
``brands.scoping`` helpers). Tracking happens for both affiliates and
advertisers regardless of whether anyone is notified — tracking ≠ notifying.

Stage progression is forward-only and driven off existing platform events
(see ``leads.services`` / ``leads.signals``):

    NEW  →  VERIFIED  →  APPROVED  →  ACTIVATED        (and, when idle, → DORMANT)

``DORMANT`` is set only by the Celery beat task; new activity reactivates a
dormant lead back to ``ACTIVATED``.
"""
from django.db import models


class Lead(models.Model):
    class Type(models.TextChoices):
        AFFILIATE = 'AFFILIATE', 'Affiliate'
        ADVERTISER = 'ADVERTISER', 'Advertiser'

    class Stage(models.TextChoices):
        NEW = 'NEW', 'New'
        VERIFIED = 'VERIFIED', 'Verified'
        APPROVED = 'APPROVED', 'Approved'
        ACTIVATED = 'ACTIVATED', 'Activated'
        DORMANT = 'DORMANT', 'Dormant'

    # Originating entity — exactly one is set. One-to-one => one Lead per entity.
    profile = models.OneToOneField(
        'user_profile.Profile',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='lead',
    )
    advertiser = models.OneToOneField(
        'offer.Advertiser',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='lead',
    )

    lead_type = models.CharField(max_length=10, choices=Type.choices)

    # Stamped at registration from the entity's brand. Brand-scoped throughout.
    brand = models.ForeignKey(
        'brands.Brand',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='leads',
    )

    # Denormalised contact snapshot (kept in sync from the entity).
    email = models.CharField(max_length=254, default='', blank=True)
    name = models.CharField(max_length=255, default='', blank=True)
    country = models.CharField(max_length=2, default='', blank=True)

    source = models.CharField(max_length=64, default='self-registration')
    pipeline_stage = models.CharField(
        max_length=10, choices=Stage.choices, default=Stage.NEW)
    notes = models.TextField(default='', blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    last_activity_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ('-last_activity_at', '-created_at')
        indexes = [
            models.Index(fields=['brand', 'pipeline_stage']),
            models.Index(fields=['lead_type']),
        ]

    def __str__(self):
        return f'{self.get_lead_type_display()}: {self.name or self.email or self.pk}'
