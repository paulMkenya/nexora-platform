"""Affiliate short links: a clean, readable URL on the brand's tracking domain
(``https://<tracking domain>/go/<slug>``) that stands in for
``/click?offer_id=…&pid=…&sub1=…``. Opening one records a normal click."""
from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models

SLUG_RE = r'^[a-z0-9](?:[a-z0-9-]{1,62}[a-z0-9])$'

slug_validator = RegexValidator(
    SLUG_RE,
    'Use 3-64 lowercase letters, numbers and dashes; start and end with a letter or number.',
)


class ShortLink(models.Model):

    class Meta:
        ordering = ('-created_at',)

    slug = models.CharField(max_length=64, unique=True, validators=[slug_validator])
    affiliate = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='short_links')
    offer = models.ForeignKey('offer.Offer', on_delete=models.CASCADE, related_name='short_links')
    label = models.CharField(max_length=128, default='', blank=True)
    sub1 = models.CharField(max_length=500, default='', blank=True)
    sub2 = models.CharField(max_length=500, default='', blank=True)
    sub3 = models.CharField(max_length=500, default='', blank=True)
    sub4 = models.CharField(max_length=500, default='', blank=True)
    sub5 = models.CharField(max_length=500, default='', blank=True)
    is_active = models.BooleanField(default=True)
    clicks = models.PositiveIntegerField(default=0)
    last_click_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.slug

    def subs(self):
        return {f'sub{i}': getattr(self, f'sub{i}') for i in range(1, 6)}
