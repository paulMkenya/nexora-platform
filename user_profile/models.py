from django.contrib.auth import get_user_model
from django.db import models

User = get_user_model()


class Profile(models.Model):
    class Role(models.TextChoices):
        AFFILIATE = 'AFFILIATE', 'Affiliate'
        ADVERTISER = 'ADVERTISER', 'Advertiser'
        AFFILIATE_MANAGER = 'AFFILIATE_MANAGER', 'Affiliate Manager'
        NETWORK_ADMIN = 'NETWORK_ADMIN', 'Network Admin'

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

    def __str__(self):
        return self.user.username
