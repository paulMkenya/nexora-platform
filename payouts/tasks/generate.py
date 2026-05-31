"""
Daily Celery beat task: generate PayoutRequests for affiliates who have
met their threshold and served out their net terms.
Idempotent — will not create duplicate requests for the same period.
"""
import logging
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.db import transaction

from project._celery import _celery
from payouts.services import get_unpaid_earnings

logger = logging.getLogger(__name__)
User = get_user_model()


@_celery.task(bind=True, max_retries=3)
def generate_payout_requests(self):
    from payouts.models import (
        PayoutSettings, PayoutRequest, PayoutMethod,
        STATUS_PENDING, METHOD_PAYPAL,
    )
    today = date.today()
    processed = 0

    for ps in PayoutSettings.objects.select_related('affiliate').iterator():
        affiliate = ps.affiliate
        paid_through = ps.paid_through or date(2000, 1, 1)
        net_days = ps.net_terms or 15

        period_end = today - timedelta(days=net_days)
        if period_end <= paid_through:
            continue

        period_start = paid_through + timedelta(days=1)

        earnings = get_unpaid_earnings(affiliate, period_start, period_end)
        if earnings < ps.min_threshold:
            continue

        with transaction.atomic():
            ps_locked = PayoutSettings.objects.select_for_update().get(pk=ps.pk)
            if PayoutRequest.objects.filter(
                affiliate=affiliate,
                period_start=period_start,
                period_end=period_end,
            ).exists():
                continue

            default_method = (
                PayoutMethod.objects
                .filter(affiliate=affiliate, is_default=True)
                .first()
            )

            req = PayoutRequest.objects.create(
                affiliate=affiliate,
                payout_method=default_method,
                amount=earnings,
                currency='USD',
                method=default_method.method if default_method else METHOD_PAYPAL,
                status=STATUS_PENDING,
                scheduled_for=today + timedelta(days=net_days),
                period_start=period_start,
                period_end=period_end,
            )
            ps_locked.paid_through = period_end
            ps_locked.save(update_fields=['paid_through', 'updated_at'])
            processed += 1
            logger.info('Created PayoutRequest #%s for affiliate %s amount=%s', req.pk, affiliate.pk, earnings)

    return f'Processed {processed} payout requests'
