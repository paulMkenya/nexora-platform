from django.contrib.auth import get_user_model
from django.db import models

from brands.archival import Archivable

User = get_user_model()


class Profile(Archivable):
    class Role(models.TextChoices):
        AFFILIATE = 'AFFILIATE', 'Affiliate'
        ADVERTISER = 'ADVERTISER', 'Advertiser'
        AFFILIATE_MANAGER = 'AFFILIATE_MANAGER', 'Affiliate Manager'
        NETWORK_ADMIN = 'NETWORK_ADMIN', 'Network Admin'

    class AffiliateStatus(models.TextChoices):
        PENDING = 'PENDING', 'Pending'
        APPROVED = 'APPROVED', 'Approved'
        REJECTED = 'REJECTED', 'Rejected'
        SUSPENDED = 'SUSPENDED', 'Suspended'

    class Theme(models.TextChoices):
        DARK = 'dark', 'Dark'
        LIGHT = 'light', 'Light'

    brand = models.ForeignKey(
        'brands.Brand',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='users',
    )
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    manager = models.ForeignKey(
        get_user_model(),
        related_name='affiliates',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.AFFILIATE,
    )
    affiliate_status = models.CharField(
        max_length=10,
        choices=AffiliateStatus.choices,
        default=AffiliateStatus.PENDING,
    )
    email_verified = models.BooleanField(default=False)
    # ISO-3166-1 alpha-2 country code (sourced from countries_plus). Blank = unset.
    country = models.CharField(max_length=2, default='', blank=True)
    # UI theme preference for the role shells (set via the topbar toggle).
    theme_preference = models.CharField(
        max_length=5,
        choices=Theme.choices,
        default=Theme.DARK,
    )

    def __str__(self):
        return self.user.username

    @property
    def is_affiliate_active(self):
        return (
            self.role == self.Role.AFFILIATE
            and self.affiliate_status == self.AffiliateStatus.APPROVED
            and self.email_verified
            and not self.is_archived
        )
