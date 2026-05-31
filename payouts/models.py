from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone


METHOD_PAYPAL = 'paypal'
METHOD_WISE = 'wise'
METHOD_PAXUM = 'paxum'
METHOD_MPESA = 'mpesa'
METHOD_BANK = 'bank'
METHOD_CRYPTO = 'crypto'

METHOD_CHOICES = [
    (METHOD_PAYPAL, 'PayPal'),
    (METHOD_WISE, 'Wise'),
    (METHOD_PAXUM, 'Paxum'),
    (METHOD_MPESA, 'M-Pesa'),
    (METHOD_BANK, 'Bank Transfer'),
    (METHOD_CRYPTO, 'Cryptocurrency'),
]

STATUS_PENDING = 'pending'
STATUS_APPROVED = 'approved'
STATUS_PROCESSING = 'processing'
STATUS_PAID = 'paid'
STATUS_FAILED = 'failed'

REQUEST_STATUS_CHOICES = [
    (STATUS_PENDING, 'Pending'),
    (STATUS_APPROVED, 'Approved'),
    (STATUS_PROCESSING, 'Processing'),
    (STATUS_PAID, 'Paid'),
    (STATUS_FAILED, 'Failed'),
]

SCHEDULE_WEEKLY = 'weekly'
SCHEDULE_BIWEEKLY = 'biweekly'
SCHEDULE_MONTHLY = 'monthly'

SCHEDULE_CHOICES = [
    (SCHEDULE_WEEKLY, 'Weekly'),
    (SCHEDULE_BIWEEKLY, 'Bi-weekly'),
    (SCHEDULE_MONTHLY, 'Monthly'),
]


class PayoutMethod(models.Model):
    class Meta:
        ordering = ('-is_default', 'created_at')
        constraints = [
            models.UniqueConstraint(
                fields=['affiliate', 'method', 'details'],
                name='payouts_method_unique_affiliate_method_details',
            )
        ]

    affiliate = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='payout_methods',
    )
    method = models.CharField(max_length=10, choices=METHOD_CHOICES)
    details = models.JSONField(default=dict, blank=True)
    is_default = models.BooleanField(default=False)
    verified = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if self.is_default:
            PayoutMethod.objects.filter(
                affiliate=self.affiliate,
                is_default=True,
            ).exclude(pk=self.pk).update(is_default=False)
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.affiliate_id} / {self.get_method_display()}'


class PayoutRequest(models.Model):
    class Meta:
        ordering = ('-created_at',)
        constraints = [
            models.UniqueConstraint(
                fields=['tx_ref'],
                name='payouts_request_unique_tx_ref',
                condition=models.Q(tx_ref__gt=''),
            )
        ]

    affiliate = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='payout_requests',
    )
    payout_method = models.ForeignKey(
        PayoutMethod,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='requests',
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=10, default='USD')
    method = models.CharField(max_length=10, choices=METHOD_CHOICES, default=METHOD_PAYPAL)
    status = models.CharField(max_length=12, choices=REQUEST_STATUS_CHOICES, default=STATUS_PENDING)
    scheduled_for = models.DateField(null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    tx_ref = models.CharField(max_length=255, default='', blank=True, db_index=True)
    period_start = models.DateField(null=True, blank=True)
    period_end = models.DateField(null=True, blank=True)
    notes = models.TextField(default='', blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def mark_paid(self, tx_ref: str = ''):
        self.status = STATUS_PAID
        self.paid_at = timezone.now()
        if tx_ref:
            self.tx_ref = tx_ref
        self.save(update_fields=['status', 'paid_at', 'tx_ref', 'updated_at'])

    def __str__(self):
        return f'PayoutRequest#{self.pk} {self.affiliate_id} ${self.amount} {self.status}'


class PayoutBatch(models.Model):
    class Meta:
        ordering = ('-created_at',)

    created_at = models.DateTimeField(auto_now_add=True)
    provider = models.CharField(max_length=10, choices=METHOD_CHOICES)
    total = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'))
    requests = models.ManyToManyField(PayoutRequest, related_name='batches', blank=True)
    csv_export = models.TextField(default='', blank=True)
    notes = models.TextField(default='', blank=True)

    def __str__(self):
        return f'Batch#{self.pk} {self.get_provider_display()} ${self.total}'


class PayoutSettings(models.Model):
    class Meta:
        verbose_name_plural = 'Payout settings'

    affiliate = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='payout_settings',
    )
    min_threshold = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal('50.00')
    )
    schedule = models.CharField(max_length=10, choices=SCHEDULE_CHOICES, default=SCHEDULE_MONTHLY)
    net_terms = models.PositiveSmallIntegerField(default=15, help_text='Net days before payout')
    paid_through = models.DateField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'PayoutSettings({self.affiliate_id})'
