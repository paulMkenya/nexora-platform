"""
Monthly invoice generation: runs on the 1st of each month via Celery beat.
Covers the previous calendar month.  Uses WeasyPrint for PDF rendering.
VAT is 16 % (Kenya standard rate) applied to all invoices.
"""
import os
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from project._celery import _celery


VAT_RATE = Decimal('16.00')


def _prev_month_range(today: date):
    first_this_month = today.replace(day=1)
    last_prev = first_this_month - timedelta(days=1)
    first_prev = last_prev.replace(day=1)
    return first_prev, last_prev


def _render_pdf(invoice, transactions) -> str:
    """Render invoice HTML → PDF with WeasyPrint; return absolute file path."""
    from django.conf import settings
    from django.template.loader import render_to_string

    html = render_to_string('billing/invoice.html', {
        'invoice': invoice,
        'transactions': transactions,
    })

    out_dir = os.path.join(settings.MEDIA_ROOT, 'invoices', str(invoice.wallet.advertiser_id))
    os.makedirs(out_dir, exist_ok=True)
    filename = f'{invoice.period_start.strftime("%Y-%m")}.pdf'
    path = os.path.join(out_dir, filename)

    try:
        import weasyprint
        weasyprint.HTML(string=html).write_pdf(path)
    except Exception:
        # WeasyPrint unavailable (system libs missing) — store HTML as fallback
        path = path.replace('.pdf', '.html')
        with open(path, 'w', encoding='utf-8') as f:
            f.write(html)

    return path


def _month_range(day: date):
    """(first, last) of the calendar month containing `day`."""
    first = day.replace(day=1)
    next_month = (first + timedelta(days=32)).replace(day=1)
    return first, next_month - timedelta(days=1)


def _last_complete_month(today: date):
    """(first, last) of the most recent month that has fully elapsed."""
    return _month_range(today.replace(day=1) - timedelta(days=1))


def _billable_months(wallet, today: date):
    """Every complete month for which this wallet has debits and no invoice yet,
    oldest first.

    Derived from the DATA rather than from "the month before today", which is
    what makes this correct no matter when it runs — see the task docstring."""
    from billing.models import TXN_DEBIT, Invoice, WalletTransaction

    _, newest_billable_end = _last_complete_month(today)
    months = {
        d.replace(day=1) for d in WalletTransaction.objects
        .filter(wallet=wallet, type=TXN_DEBIT, created_at__date__lte=newest_billable_end)
        .dates('created_at', 'month')
    }
    already = set(Invoice.objects.filter(wallet=wallet).values_list('period_start', flat=True))
    return sorted(months - already)


@_celery.task
def generate_monthly_invoices():
    """Invoice every complete month that has debits and no invoice yet.

    NOT "the previous calendar month" — that was this task's original
    definition and it was wrong twice over:

    1. IT INVOICED THE WRONG MONTH. Beat fires this at 00:05 on the 1st in
       Europe/Moscow (project/_celery.py sets that timezone), which is 21:05
       UTC on the LAST DAY of the month before. The container runs UTC, so
       date.today() returned that last day, and "previous calendar month"
       computed the month before the one intended. Every invoice was a month
       late, permanently. Deriving the period from the data instead of from
       today's date removes the dependency on when the task happens to fire.

    2. A MISSED RUN LOST A MONTH FOREVER. Nothing ever revisited a month once
       its run had passed, so a month with no successful run on the 1st was
       simply never billed — silently, since the task reported success. This
       task was in fact unregistered with Celery for its entire life (see
       project/tests/test_celery_registration.py), so NO month had ever been
       billed. A catch-up loop is what makes that recoverable rather than a
       permanent hole in revenue.

    Only COMPLETE months are billed: the current month is still accruing, and
    invoicing it early would understate it with no mechanism to correct it —
    Invoice is unique per (wallet, period_start), so the short invoice would
    win permanently.

    Idempotent. get_or_create on (wallet, period_start) matches the model's own
    unique constraint, so re-running bills nothing twice.
    """
    from billing.models import TXN_DEBIT, AdvertiserWallet, Invoice, WalletTransaction

    today = date.today()
    created_count = 0
    covered = []

    for wallet in AdvertiserWallet.objects.select_related('advertiser').all():
        for period_start in _billable_months(wallet, today):
            _, period_end = _month_range(period_start)
            debits = list(
                WalletTransaction.objects.filter(
                    wallet=wallet,
                    type=TXN_DEBIT,
                    created_at__date__gte=period_start,
                    created_at__date__lte=period_end,
                ).order_by('created_at')
            )
            if not debits:
                continue

            subtotal = sum(abs(t.amount) for t in debits).quantize(Decimal('0.01'), ROUND_HALF_UP)
            vat_amount = (subtotal * VAT_RATE / 100).quantize(Decimal('0.01'), ROUND_HALF_UP)
            total = (subtotal + vat_amount).quantize(Decimal('0.01'), ROUND_HALF_UP)

            invoice, created = Invoice.objects.get_or_create(
                wallet=wallet,
                period_start=period_start,
                defaults={
                    'period_end': period_end,
                    'subtotal': subtotal,
                    'vat_rate': VAT_RATE,
                    'vat_amount': vat_amount,
                    'total': total,
                    'status': 'draft',
                },
            )
            if not created:
                continue

            pdf_path = _render_pdf(invoice, debits)
            invoice.pdf_url = pdf_path
            invoice.save(update_fields=['pdf_url'])
            created_count += 1
            covered.append(str(period_start))

    return f'Generated {created_count} invoice(s) for period(s): {", ".join(covered) or "none"}'
