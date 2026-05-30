from django.db import models
from django.contrib.auth import get_user_model


class FraudWhitelist(models.Model):
    """IP addresses or affiliate PIDs that are exempt from fraud scoring."""

    class Meta:
        ordering = ('-created_at',)

    TYPE_IP = 'ip'
    TYPE_PID = 'pid'
    ENTRY_TYPES = (
        (TYPE_IP, 'IP Address'),
        (TYPE_PID, 'Affiliate PID'),
    )

    entry_type = models.CharField(max_length=3, choices=ENTRY_TYPES)
    value = models.CharField(max_length=64, unique=True)
    note = models.CharField(max_length=255, default='', blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        get_user_model(), on_delete=models.SET_NULL, null=True, blank=True,
    )

    def __str__(self):
        return f'{self.get_entry_type_display()}: {self.value}'
