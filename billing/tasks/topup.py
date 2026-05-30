"""
Process a confirmed payment provider top-up: credit the wallet and record the transaction.
Idempotent on external_ref.
"""
from decimal import Decimal
from django.db import transaction

from project._celery import _celery


@_celery.task(bind=True, max_retries=3)
def process_topup(self, wallet_id: int, amount_str: str, provider: str, external_ref: str):
    from billing.models import (
        AdvertiserWallet, WalletTopUp, WalletTransaction,
        TXN_TOPUP, TOPUP_COMPLETED, TOPUP_PENDING,
    )

    amount = Decimal(amount_str)
    reference = f'topup:{external_ref}'

    try:
        with transaction.atomic():
            wallet = AdvertiserWallet.objects.select_for_update().get(pk=wallet_id)

            if WalletTransaction.objects.filter(reference=reference).exists():
                return f'Already processed: {reference}'

            topup, _ = WalletTopUp.objects.get_or_create(
                wallet=wallet,
                external_ref=external_ref,
                defaults={
                    'amount': amount,
                    'provider': provider,
                    'status': TOPUP_PENDING,
                },
            )

            new_balance = wallet.balance + amount
            wallet.balance = new_balance

            # Reset low-balance alert if now above threshold
            if new_balance >= wallet.low_balance_threshold and wallet.low_balance_alert_sent:
                wallet.low_balance_alert_sent = False

            wallet.save(update_fields=['balance', 'low_balance_alert_sent', 'updated_at'])

            topup.status = TOPUP_COMPLETED
            topup.save(update_fields=['status', 'updated_at'])

            WalletTransaction.objects.create(
                wallet=wallet,
                type=TXN_TOPUP,
                amount=amount,
                balance_after=new_balance,
                description=f'{provider.title()} top-up via {external_ref}',
                reference=reference,
            )

    except Exception as exc:
        raise self.retry(exc=exc, countdown=30)

    return f'Top-up {amount} credited to wallet {wallet_id}'
