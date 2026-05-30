"""
Debit the advertiser's wallet when a conversion is approved.

Idempotent: a unique reference 'conversion:<uuid>' prevents double-charging
even if the task is retried or called twice.
"""
from decimal import Decimal
from django.db import transaction

from project._celery import _celery


def _apply_low_balance_alert(wallet, new_balance):
    if new_balance < wallet.low_balance_threshold and not wallet.low_balance_alert_sent:
        wallet.low_balance_alert_sent = True


@_celery.task(bind=True, max_retries=3)
def debit_conversion(self, conversion_id: str):
    from tracker.models import Conversion, APPROVED_STATUS
    from billing.models import AdvertiserWallet, WalletTransaction, TXN_DEBIT

    try:
        conv = (
            Conversion.objects
            .select_related('offer__advertiser')
            .get(pk=conversion_id)
        )
    except Conversion.DoesNotExist:
        return f'Conversion {conversion_id} not found'

    if conv.status != APPROVED_STATUS:
        return f'Conversion {conversion_id} not approved (status={conv.status})'

    if not conv.offer or not conv.offer.advertiser:
        return f'Conversion {conversion_id} has no advertiser'

    try:
        wallet = AdvertiserWallet.objects.get(advertiser=conv.offer.advertiser)
    except AdvertiserWallet.DoesNotExist:
        return f'No wallet for advertiser {conv.offer.advertiser_id}'

    reference = f'conversion:{conversion_id}'
    amount = Decimal(str(conv.revenue))

    if amount <= 0:
        return f'Zero/negative revenue on conversion {conversion_id}, skipping'

    try:
        with transaction.atomic():
            wallet = AdvertiserWallet.objects.select_for_update().get(pk=wallet.pk)

            if WalletTransaction.objects.filter(reference=reference).exists():
                return f'Already debited: {reference}'

            new_balance = wallet.balance - amount

            if new_balance < -wallet.credit_limit:
                return (
                    f'Insufficient balance: {wallet.balance} - {amount} = {new_balance}'
                    f' (credit_limit={wallet.credit_limit})'
                )

            wallet.balance = new_balance
            _apply_low_balance_alert(wallet, new_balance)
            wallet.save(update_fields=['balance', 'low_balance_alert_sent', 'updated_at'])

            desc = f'Conversion {conversion_id}'
            if conv.offer:
                desc += f' | {conv.offer.title}'

            WalletTransaction.objects.create(
                wallet=wallet,
                type=TXN_DEBIT,
                amount=-amount,
                balance_after=new_balance,
                description=desc,
                reference=reference,
            )

    except Exception as exc:
        raise self.retry(exc=exc, countdown=30)

    return f'Debited {amount} for {reference}; new balance={new_balance}'
