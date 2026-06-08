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
# Withdrawal-control-layer states (see payouts/control.py):
#   pending_approval — parked by the control layer (threshold / anomaly / cool-down),
#                      awaiting an authorized operator's approve/deny.
#   blocked          — refused by a velocity limit; NOT dispatched, NOT silently
#                      capped. Stays blocked until limits change or the day rolls.
#   denied           — an operator explicitly refused a pending_approval payout.
STATUS_PENDING_APPROVAL = 'pending_approval'
STATUS_BLOCKED = 'blocked'
STATUS_DENIED = 'denied'

REQUEST_STATUS_CHOICES = [
    (STATUS_PENDING, 'Pending'),
    (STATUS_APPROVED, 'Approved'),
    (STATUS_PENDING_APPROVAL, 'Pending Approval'),
    (STATUS_BLOCKED, 'Blocked'),
    (STATUS_DENIED, 'Denied'),
    (STATUS_PROCESSING, 'Processing'),
    (STATUS_PAID, 'Paid'),
    (STATUS_FAILED, 'Failed'),
]

# States the control layer parks a payout in for human/time review.
HELD_STATUSES = [STATUS_PENDING_APPROVAL, STATUS_BLOCKED]

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
            ),
            # Unique only where a provider withdrawal id exists — legacy/fiat rows
            # leave it NULL and are exempt.
            models.UniqueConstraint(
                fields=['provider_withdrawal_id'],
                name='payouts_request_unique_provider_withdrawal_id',
                condition=models.Q(provider_withdrawal_id__isnull=False),
            ),
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
    status = models.CharField(max_length=20, choices=REQUEST_STATUS_CHOICES, default=STATUS_PENDING)
    scheduled_for = models.DateField(null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    # Stamped by the withdrawal control layer the moment a payout is actually
    # released to a provider. The single source of truth for the per-day velocity
    # aggregates (count/amount per affiliate, per brand, platform-wide).
    dispatched_at = models.DateTimeField(null=True, blank=True)
    # When a time-based hold (new-address cool-down) expires. While set in the
    # future the payout cannot dispatch without an explicit operator override.
    control_hold_until = models.DateTimeField(null=True, blank=True)
    tx_ref = models.CharField(max_length=255, default='', blank=True, db_index=True)
    period_start = models.DateField(null=True, blank=True)
    period_end = models.DateField(null=True, blank=True)
    notes = models.TextField(default='', blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # --- crypto provider linkage (NOWPayments Mass Payouts; see PR #10) ---------
    # All additive + nullable — existing rows keep NULLs, no data rewrite. Populated
    # by the dispatch wiring in PR #11; nothing writes these in PR #10.
    provider_batch = models.ForeignKey(
        'CryptoPayoutBatch',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='payout_requests',
    )
    # NOWPayments' per-withdrawal id within the batch. Unique only where present
    # (partial constraint) so the many legacy NULL rows don't collide.
    provider_withdrawal_id = models.CharField(max_length=64, null=True, blank=True)
    # On-chain transaction hash once the provider settles the withdrawal.
    tx_hash = models.CharField(max_length=128, null=True, blank=True)
    # The provider's own status string for this withdrawal (distinct from our
    # internal ``status`` workflow above).
    provider_status = models.CharField(max_length=32, null=True, blank=True)

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


class CryptoPayoutBatch(models.Model):
    """A provider-side crypto payout batch (NOWPayments Mass Payouts).

    Distinct from :class:`PayoutBatch`, which is the operator's CSV-export grouping
    of fiat payout requests. This model mirrors a NOWPayments batch: under the
    single-withdrawal-per-batch model each row corresponds to one affiliate payout.

    Nothing writes this in PR #10 — the dispatch wiring that creates/verifies these
    rows lands in PR #11. The raw_* JSON fields preserve the exact provider
    responses for audit/debugging.
    """

    class Meta:
        ordering = ('-created_at',)
        verbose_name_plural = 'Crypto payout batches'

    # Free-text provider name (e.g. 'nowpayments'); kept loose so a future rail can
    # reuse this model without a choices migration.
    provider = models.CharField(max_length=32, default='nowpayments')
    # The provider's batch id. Unique so a batch is recorded exactly once.
    provider_batch_id = models.CharField(max_length=64, unique=True)
    status = models.CharField(max_length=32, default='', blank=True)
    currency = models.CharField(max_length=20, default='')
    total_amount = models.DecimalField(max_digits=18, decimal_places=8, default=Decimal('0'))
    created_at = models.DateTimeField(auto_now_add=True)
    # Stamped when the batch's 2FA verification succeeds (PR #11).
    verified_at = models.DateTimeField(null=True, blank=True)
    # Stamped when the provider reports the batch as terminally finished.
    finished_at = models.DateTimeField(null=True, blank=True)
    # Verbatim provider payloads, retained for audit/debugging.
    raw_create_response = models.JSONField(default=dict, blank=True)
    raw_last_status = models.JSONField(default=dict, blank=True)

    def __str__(self):
        return f'CryptoPayoutBatch#{self.pk} {self.provider}:{self.provider_batch_id} {self.status}'


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


# ---------------------------------------------------------------------------
# Withdrawal control layer (provider-agnostic safety net — see payouts/control.py)
# ---------------------------------------------------------------------------


class WithdrawalControlConfig(models.Model):
    """Platform-wide, owner-editable configuration for the withdrawal controls.

    A single row (``pk=1``, accessed via :meth:`load`). These are the *defaults*;
    a brand may override the per-brand-sensible ones via
    :class:`BrandWithdrawalControl`. Nothing here is env-hardcoded — the values
    live in the database and are edited in the operator UI.

    Semantics: a max amount / count of ``0`` (or ``NULL`` on an override) means
    "no limit / disabled" for that rule; the same applies to the threshold,
    cool-down and anomaly knobs.
    """

    class Meta:
        verbose_name = 'Withdrawal control configuration'
        verbose_name_plural = 'Withdrawal control configuration'

    # Master switch — when off, the layer waves every payout through (audited).
    enabled = models.BooleanField(default=True)

    # Part A — velocity limits
    per_tx_max = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('5000.00'))
    per_affiliate_day_count = models.PositiveIntegerField(default=3)
    per_affiliate_day_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('10000.00'))
    per_brand_day_count = models.PositiveIntegerField(default=50)
    per_brand_day_amount = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal('100000.00'))
    platform_day_count = models.PositiveIntegerField(default=500)
    platform_day_amount = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal('1000000.00'))

    # Part B — threshold approval
    approval_threshold = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('2000.00'))

    # Part C — new/changed-address cool-down
    new_address_cooldown_hours = models.PositiveIntegerField(default=24)

    # Part D — rule-based anomaly holds (deterministic, no ML)
    anomaly_multiple = models.DecimalField(
        max_digits=6, decimal_places=2, default=Decimal('5.00'),
        help_text='Hold a payout larger than this multiple of the affiliate historical average.')
    anomaly_min_history = models.PositiveIntegerField(
        default=3, help_text='Minimum past payouts before the multiple rule applies.')
    anomaly_burst_count = models.PositiveIntegerField(
        default=5, help_text='Hold when this many payout requests appear within the burst window.')
    anomaly_burst_window_minutes = models.PositiveIntegerField(default=60)

    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='+',
    )

    def __str__(self):
        return 'Withdrawal control configuration'

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class BrandWithdrawalControl(models.Model):
    """Per-brand overrides for the withdrawal controls.

    Every field is nullable; ``NULL`` means "inherit the platform default". Only
    the per-brand-sensible knobs are overridable here — the platform-wide daily
    caps and the burst parameters stay global on
    :class:`WithdrawalControlConfig`.
    """

    class Meta:
        verbose_name = 'Brand withdrawal control'
        verbose_name_plural = 'Brand withdrawal controls'

    brand = models.OneToOneField(
        'brands.Brand', on_delete=models.CASCADE, related_name='withdrawal_control')

    per_tx_max = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    per_affiliate_day_count = models.PositiveIntegerField(null=True, blank=True)
    per_affiliate_day_amount = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    per_brand_day_count = models.PositiveIntegerField(null=True, blank=True)
    per_brand_day_amount = models.DecimalField(max_digits=16, decimal_places=2, null=True, blank=True)
    approval_threshold = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    new_address_cooldown_hours = models.PositiveIntegerField(null=True, blank=True)
    anomaly_multiple = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)

    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'WithdrawalControl({self.brand_id})'


# Decision outcomes recorded for EVERY payout the control layer evaluates.
DECISION_ALLOWED = 'allowed'
DECISION_BLOCKED_LIMIT = 'blocked_limit'
DECISION_HELD_THRESHOLD = 'held_threshold'
DECISION_HELD_COOLDOWN = 'held_cooldown'
DECISION_HELD_ANOMALY = 'held_anomaly'
DECISION_APPROVED = 'approved'
DECISION_DENIED = 'denied'
DECISION_DISPATCH_FAILED = 'dispatch_failed'

DECISION_CHOICES = [
    (DECISION_ALLOWED, 'Allowed'),
    (DECISION_BLOCKED_LIMIT, 'Blocked by velocity limit'),
    (DECISION_HELD_THRESHOLD, 'Held for threshold approval'),
    (DECISION_HELD_COOLDOWN, 'Held for new-address cool-down'),
    (DECISION_HELD_ANOMALY, 'Held by anomaly rule'),
    (DECISION_APPROVED, 'Approved by operator'),
    (DECISION_DENIED, 'Denied by operator'),
    (DECISION_DISPATCH_FAILED, 'Dispatch failed'),
]


class PayoutDecision(models.Model):
    """Append-only audit row for every withdrawal-control decision.

    One row per decision point: the automated evaluation at dispatch (allowed /
    blocked / held) and the human action that follows (approved / denied). Never
    mutated, never deleted by the feature — the financial decision trail, mirrored
    on the impersonation audit-log discipline.
    """

    class Meta:
        ordering = ('-created_at',)
        indexes = [
            models.Index(fields=['payout_request', 'created_at']),
            models.Index(fields=['decision', 'created_at']),
        ]

    payout_request = models.ForeignKey(
        PayoutRequest, on_delete=models.CASCADE, related_name='decisions')
    decision = models.CharField(max_length=20, choices=DECISION_CHOICES)
    reason = models.TextField(default='', blank=True)
    amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'))
    brand = models.ForeignKey(
        'brands.Brand', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='payout_decisions')
    # The operator for a manual approve/deny; NULL for automated decisions.
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='payout_decisions')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    def __str__(self):
        return f'PayoutDecision#{self.pk} req={self.payout_request_id} {self.decision}'
