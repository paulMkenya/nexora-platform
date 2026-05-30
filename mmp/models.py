from django.db import models

VENDOR_APPSFLYER = 'appsflyer'
VENDOR_ADJUST = 'adjust'
VENDOR_BRANCH = 'branch'
VENDOR_SINGULAR = 'singular'
VENDOR_KOCHAVA = 'kochava'

VENDOR_CHOICES = [
    (VENDOR_APPSFLYER, 'AppsFlyer'),
    (VENDOR_ADJUST, 'Adjust'),
    (VENDOR_BRANCH, 'Branch'),
    (VENDOR_SINGULAR, 'Singular'),
    (VENDOR_KOCHAVA, 'Kochava'),
]


class MMP(models.Model):
    """Mobile Measurement Partner configuration template."""

    class Meta:
        verbose_name = 'MMP'
        verbose_name_plural = 'MMPs'

    name = models.CharField(max_length=64)
    vendor = models.CharField(max_length=20, choices=VENDOR_CHOICES, unique=True)
    # Macro placeholders: {click_id}, {app_id}, {affiliate_id}, {offer_id}
    click_template = models.CharField(max_length=1024, default='')
    # {"click_id_param": "clickid", "event_name_param": "event_name"}
    callback_patterns = models.JSONField(default=dict, blank=True)
    # ["click_id", "app_id", "affiliate_id", "offer_id"]
    required_macros = models.JSONField(default=list, blank=True)

    def __str__(self):
        return self.name


class MMPCallback(models.Model):
    """One row per inbound MMP postback, idempotent on (click_id, event_name)."""

    class Meta:
        ordering = ('-created_at',)
        constraints = [
            models.UniqueConstraint(
                fields=['click_id', 'event_name'],
                name='mmp_callback_unique_click_event',
            )
        ]

    created_at = models.DateTimeField(auto_now_add=True)
    vendor = models.CharField(max_length=20, choices=VENDOR_CHOICES, db_index=True)
    offer = models.ForeignKey(
        'offer.Offer',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='mmp_callbacks',
    )
    click_id = models.CharField(max_length=64, db_index=True)
    event_name = models.CharField(max_length=128, default='')
    raw_data = models.JSONField(default=dict, blank=True)
    processed = models.BooleanField(default=False)

    def __str__(self):
        return f'{self.vendor}:{self.click_id}:{self.event_name}'
