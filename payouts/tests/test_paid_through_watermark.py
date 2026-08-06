"""resolve_paid_through — the floor that decides what an affiliate is owed.

Replaces `ps.paid_through or date(2000, 1, 1)`, which was repeated at three
call sites (the beat task and two affiliate views) and was wrong twice:

1. The period on the first request read 2000-01-02..today — about 26 years, on
   a platform that existed for one of them. The AMOUNT was right; the PERIOD is
   what the affiliate reconciles against.

2. get_unpaid_earnings does not check whether anything was paid — it sums
   approved conversions in a window. "Unpaid" means "after paid_through" and
   nothing else. One unset field was therefore enough to pay a period twice.
"""
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model

from payouts.models import PayoutRequest, PayoutSettings, STATUS_PENDING
from payouts.services import resolve_paid_through
from tracker.models import APPROVED_STATUS, Conversion

User = get_user_model()


def _affiliate():
    return User.objects.create_user(username=f'aff_{uuid.uuid4().hex[:6]}', password='pw')


def _conversion(affiliate, when: date, payout='25.00'):
    c = Conversion.objects.create(affiliate=affiliate, status=APPROVED_STATUS, payout=Decimal(payout))
    Conversion.objects.filter(pk=c.pk).update(
        created_at=datetime(when.year, when.month, when.day, 9, 0, tzinfo=timezone.utc))
    return c


@pytest.mark.django_db
class TestResolvePaidThrough:
    def test_the_watermark_wins_when_set(self):
        aff = _affiliate()
        ps = PayoutSettings.objects.create(affiliate=aff, paid_through=date(2026, 5, 31))
        assert resolve_paid_through(aff, ps) == date(2026, 5, 31)

    def test_no_history_at_all_yields_an_empty_window_not_the_year_2000(self):
        """The old sentinel produced period_start=2000-01-02. Nothing is owed
        to an affiliate with no conversions, so the window must simply be
        empty — without inventing a date a quarter-century back."""
        aff = _affiliate()
        ps = PayoutSettings.objects.create(affiliate=aff)
        resolved = resolve_paid_through(aff, ps)
        assert resolved == date.today() - timedelta(days=1)
        assert resolved.year != 2000

    def test_first_run_starts_at_the_first_real_conversion(self):
        """With activity but no watermark, the period should describe that
        activity — not the entire history of the calendar."""
        aff = _affiliate()
        ps = PayoutSettings.objects.create(affiliate=aff)
        _conversion(aff, date(2026, 4, 10))
        _conversion(aff, date(2026, 5, 20))

        # period_start is resolved + 1 day, so this makes the first payable day
        # exactly the day of the first conversion.
        assert resolve_paid_through(aff, ps) == date(2026, 4, 9)

    def test_an_existing_request_is_a_floor_even_if_the_watermark_is_unset(self):
        """THE DOUBLE-PAY GUARD. A PayoutRequest created without advancing the
        watermark — an import, a fixture, a hand-written admin action — used to
        leave that period looking entirely unpaid, so the next run paid it
        again. Money out twice is not recoverable by an apology."""
        aff = _affiliate()
        ps = PayoutSettings.objects.create(affiliate=aff, paid_through=None)
        _conversion(aff, date(2026, 3, 1))
        PayoutRequest.objects.create(
            affiliate=aff, amount=Decimal('100.00'), currency='USD', method='paypal',
            status=STATUS_PENDING, period_start=date(2026, 3, 1), period_end=date(2026, 4, 30))

        assert resolve_paid_through(aff, ps) == date(2026, 4, 30)

    def test_the_later_of_watermark_and_request_wins(self):
        """Bias to the safe error: skipping a period is visible and fixable,
        paying twice is neither."""
        aff = _affiliate()
        ps = PayoutSettings.objects.create(affiliate=aff, paid_through=date(2026, 4, 30))
        PayoutRequest.objects.create(
            affiliate=aff, amount=Decimal('10.00'), currency='USD', method='paypal',
            status=STATUS_PENDING, period_start=date(2026, 5, 1), period_end=date(2026, 6, 30))

        assert resolve_paid_through(aff, ps) == date(2026, 6, 30)

    def test_another_affiliates_requests_are_not_a_floor(self):
        aff = _affiliate()
        other = _affiliate()
        ps = PayoutSettings.objects.create(affiliate=aff)
        _conversion(aff, date(2026, 4, 10))
        PayoutRequest.objects.create(
            affiliate=other, amount=Decimal('500.00'), currency='USD', method='paypal',
            status=STATUS_PENDING, period_start=date(2026, 1, 1), period_end=date(2026, 12, 31))

        assert resolve_paid_through(aff, ps) == date(2026, 4, 9)


@pytest.mark.django_db
class TestGenerateTaskUsesIt:
    def test_first_request_has_a_sane_period(self):
        """End to end: the beat task must no longer emit a 26-year period."""
        from payouts.tasks.generate import generate_payout_requests

        aff = _affiliate()
        PayoutSettings.objects.create(affiliate=aff, min_threshold=Decimal('10.00'), net_terms=15)
        _conversion(aff, date.today() - timedelta(days=40), payout='75.00')

        generate_payout_requests()

        req = PayoutRequest.objects.get(affiliate=aff)
        assert req.period_start.year != 2000
        assert (req.period_end - req.period_start).days < 400, (
            f'period {req.period_start}..{req.period_end} spans an implausible range')
