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


@_celery.task
def generate_monthly_invoices():
    from billing.models import (
        AdvertiserWallet, WalletTransaction, Invoice,
        TXN_DEBIT,
    )

    today = date.today()
    period_start, period_end = _prev_month_range(today)

    for wallet in AdvertiserWallet.objects.select_related('advertiser').all():
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

    return f'Invoices generated for {period_start} – {period_end}'
