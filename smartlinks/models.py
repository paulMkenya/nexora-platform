import uuid
from django.contrib.auth import get_user_model
from django.db import models


DEVICE_ANY = 'any'
DEVICE_MOBILE = 'mobile'
DEVICE_DESKTOP = 'desktop'
DEVICE_TABLET = 'tablet'

DEVICE_CHOICES = (
    (DEVICE_ANY, 'Any'),
    (DEVICE_MOBILE, 'Mobile'),
    (DEVICE_DESKTOP, 'Desktop'),
    (DEVICE_TABLET, 'Tablet'),
)


class SmartLink(models.Model):

    class Meta:
        ordering = ('name',)

    name = models.CharField(max_length=128)
    alias = models.SlugField(max_length=64, unique=True)
    default_url = models.CharField(max_length=1024)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.alias}: {self.name}'


class RoutingRule(models.Model):
    """One geo/device rule for a SmartLink. Evaluated in priority order (low = first)."""

    class Meta:
        ordering = ('priority',)

    smart_link = models.ForeignKey(SmartLink, related_name='rules', on_delete=models.CASCADE)
    priority = models.IntegerField(default=100)
    destination_url = models.CharField(max_length=1024)
    # Comma-separated ISO 3166-1 alpha-2 codes, e.g. "US,GB". Empty = match any country.
    countries = models.CharField(
        max_length=500, default='', blank=True,
        help_text='ISO-2 codes, comma-separated, e.g. US,GB. Leave empty to match any country.',
    )
    device_type = models.CharField(max_length=10, choices=DEVICE_CHOICES, default=DEVICE_ANY)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        geo = self.countries or 'any'
        return f'Rule #{self.priority} [{geo}] [{self.device_type}] → {self.destination_url[:60]}'


class SmartLinkClick(models.Model):
    """Lightweight click record for smart link routing events."""

    class Meta:
        ordering = ('-created_at',)

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    smart_link = models.ForeignKey(
        SmartLink, on_delete=models.SET_NULL, null=True, related_name='clicks',
    )
    affiliate = models.ForeignKey(
        get_user_model(), on_delete=models.SET_NULL, null=True, blank=True,
        related_name='smart_link_clicks',
    )
    ip = models.GenericIPAddressField(null=True, blank=True)
    country = models.CharField(max_length=2, default='')
    ua = models.CharField(max_length=200, default='')
    device_type = models.CharField(max_length=10, default='')
    destination_url = models.CharField(max_length=1024, default='')
    sub1 = models.CharField(max_length=500, default='')
    sub2 = models.CharField(max_length=500, default='')
