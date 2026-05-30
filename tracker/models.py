import uuid
from django.db import models
from offer.models import Advertiser, Offer, Goal, Currency
from django.contrib.auth import get_user_model


class Click(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    sub1 = models.CharField(max_length=500, default="")
    sub2 = models.CharField(max_length=500, default="")
    sub3 = models.CharField(max_length=500, default="")
    sub4 = models.CharField(max_length=500, default="")
    sub5 = models.CharField(max_length=500, default="")
    ip = models.GenericIPAddressField()
    country = models.CharField(max_length=2, default="")
    ua = models.CharField(max_length=200, default="")
    revenue = models.DecimalField(max_digits=7, decimal_places=2)
    payout = models.DecimalField(max_digits=7, decimal_places=2)

    offer = models.ForeignKey(
        Offer,
        related_name='clicks',
        on_delete=models.SET_NULL,
        null=True
    )

    affiliate = models.ForeignKey(
        get_user_model(),
        related_name='clicks',
        on_delete=models.SET_NULL,
        null=True
    )

    affiliate_manager = models.ForeignKey(
        get_user_model(),
        # related_name='clicks',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    # ── Fraud fields ───────────────────────────────────────────────────────
    fraud_score = models.IntegerField(default=0)
    fraud_reasons = models.JSONField(default=list, blank=True)
    is_proxy = models.BooleanField(default=False)
    is_datacenter = models.BooleanField(default=False)
    is_bot = models.BooleanField(default=False)


APPROVED_STATUS = 'approved'
HOLD_STATUS = 'hold'
REJECTED_STATUS = 'rejected'
PENDING_STATUS = 'pending'
conversion_statuses = (
    (APPROVED_STATUS, 'Approved',),
    (HOLD_STATUS, 'Hold',),
    (REJECTED_STATUS, 'Rejected',),
    (PENDING_STATUS, 'Pending',),
)


class Conversion(models.Model):

    class Meta:
        ordering = ('-created_at',)

    id = models.UUIDField(
        primary_key=True, default=uuid.uuid4, editable=False)
    click_id = models.UUIDField(editable=False, null=True, default=None)
    created_at = models.DateTimeField(auto_now_add=True)
    click_date = models.DateTimeField(null=True, default=None, blank=True)
    sub1 = models.CharField(max_length=500, default="", blank=True)
    sub2 = models.CharField(max_length=500, default="", blank=True)
    sub3 = models.CharField(max_length=500, default="", blank=True)
    sub4 = models.CharField(max_length=500, default="", blank=True)
    sub5 = models.CharField(max_length=500, default="", blank=True)
    revenue = models.DecimalField(max_digits=7, decimal_places=2, default=.0)
    payout = models.DecimalField(max_digits=7, decimal_places=2, default=.0)
    ip = models.GenericIPAddressField(null=True, default=None, blank=True)
    country = models.CharField(max_length=2, default="", blank=True)
    ua = models.CharField(max_length=200, default="", blank=True)
    goal_value = models.CharField(max_length=20, default="")
    status = models.CharField(
        max_length=10, choices=conversion_statuses, default=REJECTED_STATUS)
    sum = models.FloatField(default=0.0)
    comment = models.CharField(max_length=128, default='', blank=True)

    # ── Fraud fields ───────────────────────────────────────────────────────
    fraud_score = models.IntegerField(default=0)
    fraud_reasons = models.JSONField(default=list, blank=True)
    auto_rejected_reason = models.CharField(max_length=128, default='', blank=True)

    goal = models.ForeignKey(
        Goal,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    currency = models.ForeignKey(
        Currency,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    offer = models.ForeignKey(
        Offer,
        related_name='conversions',
        on_delete=models.SET_NULL,
        null=True
    )

    affiliate = models.ForeignKey(
        get_user_model(),
        related_name='conversions',
        on_delete=models.SET_NULL,
        null=True
    )

    affiliate_manager = models.ForeignKey(
        get_user_model(),
        # related_name='conversions',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )


# ── Inbound postback logging ───────────────────────────────────────────────

HMAC_OK      = 'ok'
HMAC_FAIL    = 'fail'
HMAC_MISSING = 'missing'
HMAC_SKIP    = 'skip'

HMAC_STATUSES = (
    (HMAC_OK,      'OK — signature matched'),
    (HMAC_FAIL,    'Fail — signature mismatch'),
    (HMAC_MISSING, 'Missing — no sig param'),
    (HMAC_SKIP,    'Skip — no key registered or flag off'),
)


class InboundPostbackLog(models.Model):
    """One row per inbound S2S postback received at /postback."""

    class Meta:
        ordering = ('-received_at',)

    received_at  = models.DateTimeField(auto_now_add=True)
    advertiser   = models.ForeignKey(
        Advertiser,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='inbound_postback_logs',
    )
    click_id     = models.CharField(max_length=64, default='')
    status_param = models.CharField(max_length=20,  default='')
    sum_param    = models.CharField(max_length=32,  default='')
    query_string = models.CharField(max_length=1000, default='')
    hmac_status  = models.CharField(max_length=10, choices=HMAC_STATUSES, default=HMAC_SKIP)
    response_code = models.IntegerField(default=200)
    note         = models.CharField(max_length=255, default='', blank=True)
