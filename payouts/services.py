"""Earnings helpers for affiliate payout calculations."""
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db.models import Sum

from tracker.models import Conversion, APPROVED_STATUS

User = get_user_model()


def get_unpaid_earnings(affiliate, since: date, until: date) -> Decimal:
    """
    Sum approved conversions for the affiliate in [since, until] (inclusive).
    Excludes any conversions that were fraud-rejected (status=REJECTED).
    """
    total = (
        Conversion.objects
        .filter(
            affiliate=affiliate,
            status=APPROVED_STATUS,
            created_at__date__gte=since,
            created_at__date__lte=until,
        )
        .aggregate(total=Sum('payout'))['total']
    )
    return total or Decimal('0.00')


def get_or_create_payout_settings(affiliate):
    from payouts.models import PayoutSettings
    settings_obj, _ = PayoutSettings.objects.get_or_create(affiliate=affiliate)
    return settings_obj
