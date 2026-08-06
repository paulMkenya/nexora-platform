"""Earnings helpers for affiliate payout calculations."""
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db.models import Max, Min, Sum

from tracker.models import Conversion, APPROVED_STATUS

User = get_user_model()


def resolve_paid_through(affiliate, settings_obj) -> date:
    """The watermark below which this affiliate's earnings are already
    accounted for. Everything after it is payable.

    Replaces a bare ``settings_obj.paid_through or date(2000, 1, 1)``, which was
    repeated at three call sites and was wrong in two ways:

    1. THE PERIOD WAS NONSENSE. With no watermark the first request came out
       spanning 2000-01-02 to today, ~26 years, on a platform that did not
       exist for 25 of them. The AMOUNT was right — get_unpaid_earnings only
       sums conversions that exist — but the period is what appears on the
       affiliate's statement and what reconciliation is done against. Here the
       floor is the day before the affiliate's first approved conversion, so
       the period describes real activity.

    2. IT TRUSTED ONE FIELD FOR A MONEY DECISION. get_unpaid_earnings does not
       check whether anything was paid; it sums approved conversions in a
       window. "Unpaid" means "after paid_through" and nothing else. Both
       current writers advance the watermark in the same transaction that
       creates the request, so they agree — but if a PayoutRequest is ever
       created without that happening (an import, a fixture, a hand-written
       admin action, a half-applied migration), the watermark says nothing was
       paid and that period gets paid a SECOND time. Taking the max period_end
       of existing requests as a floor makes the requests themselves
       corroborate the watermark, so the two must both fail to cause a
       double-pay.

    Returns a date such that the payable window is (returned_date, ...] —
    callers add a day to get their period_start, as before.
    """
    from payouts.models import PayoutRequest

    candidates = []
    if settings_obj is not None and settings_obj.paid_through:
        candidates.append(settings_obj.paid_through)

    covered = (
        PayoutRequest.objects
        .filter(affiliate=affiliate)
        .aggregate(latest=Max('period_end'))['latest']
    )
    if covered:
        candidates.append(covered)

    if candidates:
        # The LATEST of the two: paying twice is unrecoverable, skipping a
        # period is visible and fixable. Bias to the safe error.
        return max(candidates)

    first_conversion = (
        Conversion.objects
        .filter(affiliate=affiliate, status=APPROVED_STATUS)
        .aggregate(first=Min('created_at'))['first']
    )
    if first_conversion:
        return first_conversion.date() - timedelta(days=1)

    # No conversions and no history: nothing is owed, so nothing is payable.
    # Yesterday keeps the window empty without inventing a date.
    return date.today() - timedelta(days=1)


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
