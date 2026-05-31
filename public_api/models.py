import secrets
import uuid

from django.contrib.auth import get_user_model
from django.db import models

User = get_user_model()

EVENT_CHOICES = [
    ('offer.created', 'Offer Created'),
    ('conversion.approved', 'Conversion Approved'),
    ('payout.paid', 'Payout Paid'),
]


class APIKey(models.Model):
    """Per-user API key for machine-to-machine authentication."""

    client_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    secret = models.CharField(max_length=64, unique=True, db_index=True, editable=False)
    name = models.CharField(max_length=64)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='api_keys')
    is_active = models.BooleanField(default=True)
    requests_per_hour = models.IntegerField(default=1000)
    last_used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('-created_at',)

    def __str__(self):
        return f'{self.name} ({self.user})'

    @classmethod
    def generate(cls, user: User, name: str, requests_per_hour: int = 1000) -> 'APIKey':
        return cls.objects.create(
            user=user,
            name=name,
            secret=secrets.token_urlsafe(48),
            requests_per_hour=requests_per_hour,
        )


class WebhookEndpoint(models.Model):
    """Admin-configured endpoint to receive signed event notifications."""

    brand = models.ForeignKey('brands.Brand', on_delete=models.CASCADE, related_name='webhook_endpoints')
    url = models.URLField(max_length=500)
    secret = models.CharField(max_length=64)
    events = models.JSONField(default=list, help_text='List of event names to subscribe to.')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('-created_at',)

    def __str__(self):
        return f'{self.url} [{self.brand}]'

    @classmethod
    def for_event(cls, brand_id: int, event: str):
        return cls.objects.filter(brand_id=brand_id, is_active=True, events__contains=[event])


class WebhookDelivery(models.Model):
    STATUS_PENDING = 'pending'
    STATUS_DELIVERED = 'delivered'
    STATUS_FAILED = 'failed'

    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_DELIVERED, 'Delivered'),
        (STATUS_FAILED, 'Failed'),
    ]

    RETRY_BACKOFFS = [60, 300, 1800]  # seconds: 1 min, 5 min, 30 min

    endpoint = models.ForeignKey(WebhookEndpoint, on_delete=models.CASCADE, related_name='deliveries')
    event = models.CharField(max_length=64)
    payload = models.JSONField()
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING)
    attempts = models.IntegerField(default=0)
    next_retry_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(default='', blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    delivered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ('-created_at',)

    def __str__(self):
        return f'{self.event} → {self.endpoint.url} [{self.status}]'
