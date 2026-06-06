"""Platform-owner sales funnel — the PLATFORM's own customer pipeline.

A ``PlatformLead`` is a prospect who wants their *own* white-label network on
the platform (a brand, an advertiser, a network/agency, or a solo affiliate).
This is **strictly distinct** from ``leads.Lead``: that tracks the entities that
register *inside* a brand (a brand's own affiliates/advertisers), and is
brand-scoped. A ``PlatformLead`` is the platform owner's *own* business data —
network-wide, superuser-only, never shown to a brand operator.

Captured by the public ``/get-started/`` form; worked by the owner in the
owner-only pipeline. The sales stage is **manual** — the owner moves it as the
deal progresses (no auto-advance). Verticals and traffic sources reuse the
existing ``offer.Category`` / ``offer.TrafficSource`` reference data so the
funnel speaks the same taxonomy as the rest of the platform.
"""
from django.db import models


class PlatformLead(models.Model):
    class LeadType(models.TextChoices):
        SOLO = 'SOLO', 'Solo affiliate / publisher'
        ADVERTISER = 'ADVERTISER', 'Advertiser / brand running offers'
        NETWORK = 'NETWORK', 'Network / agency wanting a white-label platform'
        OTHER = 'OTHER', 'Other'

    class Timeline(models.TextChoices):
        NOW = 'NOW', 'Now'
        SOON = 'SOON', '1–3 months'
        EXPLORING = 'EXPLORING', 'Just exploring'

    class Stage(models.TextChoices):
        NEW = 'NEW', 'New'
        CONTACTED = 'CONTACTED', 'Contacted'
        QUALIFIED = 'QUALIFIED', 'Qualified'
        DEMO_PROPOSAL = 'DEMO_PROPOSAL', 'Demo / proposal'
        NEGOTIATION = 'NEGOTIATION', 'Negotiation'
        WON = 'WON', 'Won'
        LOST = 'LOST', 'Lost'

    lead_type = models.CharField(max_length=12, choices=LeadType.choices)

    # Universal fields.
    name = models.CharField(max_length=255)
    email = models.EmailField(max_length=254)
    phone = models.CharField(max_length=40, blank=True, default='')
    company = models.CharField(max_length=255, blank=True, default='')
    country = models.CharField(max_length=2, blank=True, default='')  # ISO alpha-2
    website = models.CharField(max_length=500, blank=True, default='')

    # Qualifying fields — all optional server-side (shown adaptively per type).
    scale = models.CharField(
        max_length=255, blank=True, default='',
        help_text='Monthly volume / scale — clicks or conversions per month, or '
                  'affiliate count for networks.')
    verticals = models.ManyToManyField(
        'offer.Category', blank=True, related_name='platform_leads')
    traffic_sources = models.ManyToManyField(
        'offer.TrafficSource', blank=True, related_name='platform_leads')
    pain = models.TextField(blank=True, default='', help_text='Current pain / why looking.')
    timeline = models.CharField(
        max_length=10, choices=Timeline.choices, blank=True, default='')
    budget = models.CharField(max_length=120, blank=True, default='')

    # Attribution — how they heard about us.
    source = models.CharField(max_length=255, blank=True, default='')

    # Owner-managed pipeline state. MANUAL — no auto-advance.
    sales_stage = models.CharField(
        max_length=14, choices=Stage.choices, default=Stage.NEW)
    notes = models.TextField(blank=True, default='')

    created_at = models.DateTimeField(auto_now_add=True)
    last_contact_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ('-created_at',)
        indexes = [
            models.Index(fields=['sales_stage']),
            models.Index(fields=['lead_type']),
        ]

    def __str__(self):
        return f'{self.get_lead_type_display()}: {self.name or self.email or self.pk}'
