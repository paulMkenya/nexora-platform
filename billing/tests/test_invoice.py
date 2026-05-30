"""
Tests: monthly invoice generation — correct maths, idempotency, no-activity skip.
"""
import uuid
from datetime import date
from decimal import Decimal
import pytest
from unittest import mock

from offer.models import Advertiser
from billing.models import (
    AdvertiserWallet, WalletTransaction, Invoice,
    TXN_DEBIT,
)
from billing.tasks.invoice import generate_monthly_invoices, _prev_month_range, VAT_RATE


def _make_wallet():
    from django.contrib.auth import get_user_model
    u = get_user_model().objects.create_user(username=f'u_{uuid.uuid4().hex[:6]}', password='pw')
    adv = Advertiser.objects.create(company='Test Co', email='t@example.com', user=u)
    return AdvertiserWallet.objects.create(advertiser=adv, balance=Decimal('200.00'))


def _backdate_txn(txn, dt):
    WalletTransaction.objects.filter(pk=txn.pk).update(created_at=dt)


@pytest.mark.django_db
class TestPrevMonthRange:

    def test_first_of_month(self):
        today = date(2026, 5, 1)
        start, end = _prev_month_range(today)
        assert start == date(2026, 4, 1)
        assert end == date(2026, 4, 30)

    def test_mid_month(self):
        today = date(2026, 5, 15)
        start, end = _prev_month_range(today)
        assert start == date(2026, 4, 1)
        assert end == date(2026, 4, 30)

    def test_january_wraps_to_december(self):
        today = date(2026, 1, 10)
        start, end = _prev_month_range(today)
        assert start == date(2025, 12, 1)
        assert end == date(2025, 12, 31)


@pytest.mark.django_db
class TestGenerateMonthlyInvoices:

    def test_invoice_created_with_correct_totals(self):
        wallet = _make_wallet()
        period_start = date(2026, 4, 1)

        # Seed two debit transactions in April 2026
        t1 = WalletTransaction.objects.create(
            wallet=wallet, type=TXN_DEBIT, amount=Decimal('-50.00'),
            balance_after=Decimal('150.00'), reference=f'conv:{uuid.uuid4().hex}')
        t2 = WalletTransaction.objects.create(
            wallet=wallet, type=TXN_DEBIT, amount=Decimal('-30.00'),
            balance_after=Decimal('120.00'), reference=f'conv:{uuid.uuid4().hex}')
        _backdate_txn(t1, '2026-04-10 10:00:00')
        _backdate_txn(t2, '2026-04-20 15:00:00')

        with mock.patch('billing.tasks.invoice.date') as mock_date:
            mock_date.today.return_value = date(2026, 5, 1)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            with mock.patch('billing.tasks.invoice._render_pdf', return_value='/media/invoices/1/2026-04.pdf'):
                generate_monthly_invoices()

        inv = Invoice.objects.get(wallet=wallet, period_start=period_start)
        assert inv.subtotal == Decimal('80.00')
        expected_vat = (Decimal('80.00') * VAT_RATE / 100).quantize(Decimal('0.01'))
        assert inv.vat_amount == expected_vat
        assert inv.total == Decimal('80.00') + expected_vat

    def test_no_invoice_when_no_debits(self):
        wallet = _make_wallet()
        with mock.patch('billing.tasks.invoice.date') as mock_date:
            mock_date.today.return_value = date(2026, 5, 1)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            with mock.patch('billing.tasks.invoice._render_pdf', return_value=''):
                generate_monthly_invoices()

        assert Invoice.objects.filter(wallet=wallet).count() == 0

    def test_invoice_idempotent(self):
        wallet = _make_wallet()
        period_start = date(2026, 4, 1)

        t = WalletTransaction.objects.create(
            wallet=wallet, type=TXN_DEBIT, amount=Decimal('-25.00'),
            balance_after=Decimal('175.00'), reference=f'conv:{uuid.uuid4().hex}')
        _backdate_txn(t, '2026-04-05 09:00:00')

        with mock.patch('billing.tasks.invoice.date') as mock_date:
            mock_date.today.return_value = date(2026, 5, 1)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            with mock.patch('billing.tasks.invoice._render_pdf', return_value=''):
                generate_monthly_invoices()
                generate_monthly_invoices()  # second run

        assert Invoice.objects.filter(wallet=wallet, period_start=period_start).count() == 1

    def test_vat_16_percent_applied(self):
        wallet = _make_wallet()
        t = WalletTransaction.objects.create(
            wallet=wallet, type=TXN_DEBIT, amount=Decimal('-100.00'),
            balance_after=Decimal('100.00'), reference=f'conv:{uuid.uuid4().hex}')
        _backdate_txn(t, '2026-04-15 12:00:00')

        with mock.patch('billing.tasks.invoice.date') as mock_date:
            mock_date.today.return_value = date(2026, 5, 1)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            with mock.patch('billing.tasks.invoice._render_pdf', return_value=''):
                generate_monthly_invoices()

        inv = Invoice.objects.get(wallet=wallet, period_start=date(2026, 4, 1))
        assert inv.vat_rate == Decimal('16.00')
        assert inv.vat_amount == Decimal('16.00')
        assert inv.total == Decimal('116.00')
