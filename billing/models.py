from decimal import Decimal
from django.db import models
from offer.models import Advertiser


# ── provider / status choices ───────────────────────────────────────────────

PROVIDER_STRIPE = 'stripe'
PROVIDER_PAYSTACK = 'paystack'
PROVIDER_MANUAL = 'manual'
PROVIDER_CHOICES = [
    (PROVIDER_STRIPE, 'Stripe'),
    (PROVIDER_PAYSTACK, 'Paystack'),
    (PROVIDER_MANUAL, 'Manual'),
]

TOPUP_PENDING = 'pending'
TOPUP_COMPLETED = 'completed'
TOPUP_FAILED = 'failed'
TOPUP_STATUS_CHOICES = [
    (TOPUP_PENDING, 'Pending'),
    (TOPUP_COMPLETED, 'Completed'),
    (TOPUP_FAILED, 'Failed'),
]

TXN_TOPUP = 'topup'
TXN_DEBIT = 'debit'
TXN_REFUND = 'refund'
TXN_ADJUSTMENT = 'adjustment'
TXN_TYPE_CHOICES = [
    (TXN_TOPUP, 'Top-up'),
    (TXN_DEBIT, 'Debit'),
    (TXN_REFUND, 'Refund'),
    (TXN_ADJUSTMENT, 'Adjustment'),
]

INVOICE_DRAFT = 'draft'
INVOICE_SENT = 'sent'
INVOICE_PAID = 'paid'
INVOICE_STATUS_CHOICES = [
    (INVOICE_DRAFT, 'Draft'),
    (INVOICE_SENT, 'Sent'),
    (INVOICE_PAID, 'Paid'),
]


# ── models ───────────────────────────────────────────────────────────────────

class AdvertiserWallet(models.Model):
    class Meta:
        verbose_name = 'Advertiser Wallet'

    advertiser = models.OneToOneField(
        Advertiser,
        on_delete=models.CASCADE,
        related_name='wallet',
    )
    balance = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    currency = models.CharField(max_length=3, default='USD')
    # Negative balance is allowed down to -credit_limit
    credit_limit = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    low_balance_threshold = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('10.00'))
    low_balance_alert_sent = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'{self.advertiser} — {self.balance} {self.currency}'


class WalletTopUp(models.Model):
    class Meta:
        ordering = ('-created_at',)

    wallet = models.ForeignKey(AdvertiserWallet, on_delete=models.CASCADE, related_name='topups')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    provider = models.CharField(max_length=20, choices=PROVIDER_CHOICES)
    status = models.CharField(max_length=20, choices=TOPUP_STATUS_CHOICES, default=TOPUP_PENDING)
    # Stripe PaymentIntent ID or Paystack reference
    external_ref = models.CharField(max_length=255, default='', blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'{self.provider} {self.amount} [{self.status}]'


class WalletTransaction(models.Model):
    class Meta:
        ordering = ('-created_at',)
        constraints = [
            # Prevent double-processing: reference must be unique when non-empty
            models.UniqueConstraint(
                fields=['reference'],
                name='billing_txn_unique_reference',
                condition=models.Q(reference__gt=''),
            )
        ]

    wallet = models.ForeignKey(AdvertiserWallet, on_delete=models.CASCADE, related_name='transactions')
    type = models.CharField(max_length=20, choices=TXN_TYPE_CHOICES)
    # Positive = credit (topup/refund), negative = debit
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    balance_after = models.DecimalField(max_digits=12, decimal_places=2)
    description = models.CharField(max_length=255, default='', blank=True)
    # Unique idempotency key, e.g. "conversion:<uuid>" or "topup:<ext_ref>"
    reference = models.CharField(max_length=128, default='', blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.type} {self.amount} → {self.balance_after}'


class Invoice(models.Model):
    class Meta:
        ordering = ('-period_start',)
        constraints = [
            models.UniqueConstraint(
                fields=['wallet', 'period_start'],
                name='billing_invoice_unique_wallet_period',
            )
        ]

    wallet = models.ForeignKey(AdvertiserWallet, on_delete=models.CASCADE, related_name='invoices')
    period_start = models.DateField()
    period_end = models.DateField()
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    vat_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('16.00'))
    vat_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    status = models.CharField(max_length=20, choices=INVOICE_STATUS_CHOICES, default=INVOICE_DRAFT)
    pdf_url = models.CharField(max_length=512, default='', blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'Invoice {self.period_start} — {self.wallet.advertiser}'
