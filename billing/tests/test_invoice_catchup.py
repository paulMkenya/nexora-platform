"""Invoice generation must not depend on WHICH DAY it runs.

The original task billed "the previous calendar month relative to date.today()".
That was wrong twice, and both faults are silent — the task returns success
either way:

1. It billed the WRONG month. Beat fires at 00:05 on the 1st in Europe/Moscow
   (project/_celery.py), which is 21:05 UTC on the LAST DAY of the month before.
   Containers run UTC, so date.today() was that last day and "previous month"
   resolved one month too early. Every invoice a month late, forever.

2. A missed run lost a month permanently. Nothing revisited a month once its
   run had passed. The task was in fact unregistered with Celery for its whole
   life, so no month had ever been billed at all.

These tests drive the task at the awkward times rather than at a convenient
one, because the convenient time was never the problem.
"""
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from billing.models import TXN_DEBIT, AdvertiserWallet, Invoice, WalletTransaction
from billing.tasks.invoice import generate_monthly_invoices
from offer.models import Advertiser


def _wallet():
    from django.contrib.auth import get_user_model
    u = get_user_model().objects.create_user(username=f'u_{uuid.uuid4().hex[:6]}', password='pw')
    adv = Advertiser.objects.create(company='Test Co', email=f'{uuid.uuid4().hex[:6]}@example.com', user=u)
    return AdvertiserWallet.objects.create(advertiser=adv, balance=Decimal('1000.00'))


def _debit(wallet, when: date, amount='100.00'):
    """A debit as the app really stores one: NEGATIVE amount plus the running
    balance_after (non-null in the schema). The task sums abs(amount)."""
    txn = WalletTransaction.objects.create(
        wallet=wallet, type=TXN_DEBIT, amount=-Decimal(amount),
        balance_after=Decimal('0.00'), reference=f'conv:{uuid.uuid4().hex}')
    WalletTransaction.objects.filter(pk=txn.pk).update(
        created_at=datetime(when.year, when.month, when.day, 12, 0, tzinfo=timezone.utc))
    return txn


@pytest.fixture
def frozen(monkeypatch):
    """Pin date.today() inside the task module only."""
    def _set(d):
        import billing.tasks.invoice as mod

        class _D(date):
            @classmethod
            def today(cls):
                return d
        monkeypatch.setattr(mod, 'date', _D)
    return _set


@pytest.mark.django_db
class TestRunsAtTheAwkwardTime:
    def test_billing_the_last_day_of_a_month_still_bills_that_month(self, frozen):
        """THE TIMEZONE BUG. Beat's 'the 1st, Moscow' lands on the last day of
        the previous month in UTC. The old code then billed the month before
        THAT, so June's run produced May's invoice. June must be billed."""
        w = _wallet()
        _debit(w, date(2026, 6, 15))
        frozen(date(2026, 6, 30))  # what date.today() actually returns at fire time

        generate_monthly_invoices()

        periods = set(Invoice.objects.filter(wallet=w).values_list('period_start', flat=True))
        assert date(2026, 6, 1) not in periods, 'June is still accruing on 30 June — too early to bill'
        assert periods == set(), 'nothing complete yet, so nothing billed'

        frozen(date(2026, 7, 31))  # the run that is nominally "1 August, Moscow"
        generate_monthly_invoices()

        periods = set(Invoice.objects.filter(wallet=w).values_list('period_start', flat=True))
        assert date(2026, 6, 1) in periods, 'June is complete and must be billed, not skipped'

    def test_a_mid_month_run_bills_every_complete_month(self, frozen):
        w = _wallet()
        _debit(w, date(2026, 6, 10))
        frozen(date(2026, 7, 17))

        generate_monthly_invoices()

        assert Invoice.objects.filter(wallet=w, period_start=date(2026, 6, 1)).exists()


@pytest.mark.django_db
class TestCatchUp:
    def test_every_missed_month_is_billed_not_just_the_last_one(self, frozen):
        """The whole point of the fix. Three months of debits accumulated while
        the task was unregistered; one run must bill all three."""
        w = _wallet()
        for m in (3, 4, 5):
            _debit(w, date(2026, m, 12), amount='50.00')
        frozen(date(2026, 6, 5))

        generate_monthly_invoices()

        periods = sorted(Invoice.objects.filter(wallet=w).values_list('period_start', flat=True))
        assert periods == [date(2026, 3, 1), date(2026, 4, 1), date(2026, 5, 1)]

    def test_the_current_month_is_never_billed_early(self, frozen):
        """It is still accruing, and Invoice is unique per (wallet,
        period_start) — a short invoice written now would win permanently."""
        w = _wallet()
        _debit(w, date(2026, 6, 3))
        frozen(date(2026, 6, 20))

        generate_monthly_invoices()

        assert not Invoice.objects.filter(wallet=w, period_start=date(2026, 6, 1)).exists()

    def test_rerunning_bills_nothing_twice(self, frozen):
        w = _wallet()
        _debit(w, date(2026, 4, 8))
        frozen(date(2026, 6, 2))

        generate_monthly_invoices()
        generate_monthly_invoices()
        generate_monthly_invoices()

        assert Invoice.objects.filter(wallet=w).count() == 1

    def test_a_month_with_no_debits_gets_no_invoice(self, frozen):
        w = _wallet()
        _debit(w, date(2026, 3, 9))
        _debit(w, date(2026, 5, 9))
        frozen(date(2026, 6, 2))

        generate_monthly_invoices()

        periods = sorted(Invoice.objects.filter(wallet=w).values_list('period_start', flat=True))
        assert periods == [date(2026, 3, 1), date(2026, 5, 1)], 'April had no activity'

    def test_amounts_are_per_month_not_pooled(self, frozen):
        w = _wallet()
        _debit(w, date(2026, 3, 4), amount='100.00')
        _debit(w, date(2026, 4, 4), amount='250.00')
        frozen(date(2026, 5, 2))

        generate_monthly_invoices()

        march = Invoice.objects.get(wallet=w, period_start=date(2026, 3, 1))
        april = Invoice.objects.get(wallet=w, period_start=date(2026, 4, 1))
        assert march.subtotal == Decimal('100.00')
        assert april.subtotal == Decimal('250.00')
        assert march.period_end == date(2026, 3, 31)
        assert april.period_end == date(2026, 4, 30)
