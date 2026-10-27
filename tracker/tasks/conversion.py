from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from project._celery import _celery
from tracker.models import (
    Click,
    Conversion,
    HOLD_STATUS,
    REJECTED_STATUS,
)
from offer.models import Offer, Payout


def offer_rule_verdict(click, offer):
    """Apply the offer's delivery controls to a payable conversion.

    Returns (status, comment) when a rule overrides the status, else None.
    Carrier first (it is a property of the click, a cap is not), then the
    daily cap. Rejected conversions never count towards the cap.
    """
    allowed = offer.asn_allow_list()
    if allowed:
        if click.asn is None:
            return HOLD_STATUS, 'Carrier unknown - review'
        if click.asn not in allowed:
            return REJECTED_STATUS, f'Carrier not allowed (AS{click.asn} {click.isp})'[:128]

    if offer.daily_cap:
        today = (
            Conversion.objects
            .filter(offer_id=offer.id, created_at__date=timezone.localdate())
            .exclude(status=REJECTED_STATUS)
            .count()
        )
        if today >= offer.daily_cap:
            return REJECTED_STATUS, f'Daily cap reached ({offer.daily_cap})'
    return None


@_celery.task
def conversion(data):
    try:
        click = Click.objects.get(pk=data['click_id'])
    except (Click.DoesNotExist, ValidationError, ValueError):
        return f"Click not found. click_id: {data['click_id']}"
    txid = (data.get('txid') or '')[:64]

    existing_conversion = (
        Conversion.objects
        .filter(click_id=click.id, goal_value=data['goal'])
        .first()
    )
    if existing_conversion and data.get('status'):
        if existing_conversion.status == HOLD_STATUS:
            existing_conversion.status = data.get('status')
            existing_conversion.save()
            if existing_conversion.status not in (HOLD_STATUS, REJECTED_STATUS):
                from billing.tasks.debit import debit_conversion
                debit_conversion.delay(str(existing_conversion.id))
            return f"Processed conversion for click_id: {data['click_id']}"

    duplicate = bool(existing_conversion)
    # Serialise conversions per offer so the daily-cap count can't race.
    with transaction.atomic():
        if click.offer_id:
            Offer.objects.select_for_update().filter(pk=click.offer_id).first()
        conversion = _record(click, data, txid, duplicate)

    # Chain fraud scoring after conversion is persisted
    from fraud.tasks import score_conversion_fraud
    score_conversion_fraud.delay(str(conversion.id))

    # Debit advertiser wallet for approved conversions
    from billing.tasks.debit import debit_conversion
    debit_conversion.delay(str(conversion.id))

    return f"Processed conversion for click_id: {data['click_id']}"


def _record(click, data, txid, duplicate):
    conversion = Conversion()

    payout = (
        Payout.objects
        .filter(
            offer_id=click.offer_id,
            goal_value=data['goal'],
            countries__in=[click.country]
        )
        .first()
    )

    if payout:
        conversion.revenue = payout.revenue
        conversion.payout = payout.payout
        conversion.goal = payout.goal
        conversion.currency = payout.currency

        if data.get('status'):
            conversion.status = data.get('status')
        else:
            conversion.status = HOLD_STATUS

        if duplicate:
            conversion.status = REJECTED_STATUS
            conversion.comment = 'Duplicate Click ID'
        elif txid and Conversion.objects.filter(offer_id=click.offer_id, txid=txid).exists():
            conversion.status = REJECTED_STATUS
            conversion.comment = 'Duplicate txid'
        elif conversion.status != REJECTED_STATUS:
            verdict = offer_rule_verdict(click, click.offer)
            if verdict:
                conversion.status, conversion.comment = verdict
    else:
        conversion.revenue = 0
        conversion.payout = 0
        conversion.status = REJECTED_STATUS
        conversion.comment = 'Payout not found'

    conversion.click_id = click.id
    conversion.click_date = click.created_at

    conversion.offer_id = click.offer.id
    conversion.affiliate_id = click.affiliate.id
    conversion.affiliate_manager = click.affiliate.profile.manager
    conversion.sub1 = click.sub1
    conversion.sub2 = click.sub2
    conversion.sub3 = click.sub3
    conversion.sub4 = click.sub4
    conversion.sub5 = click.sub5
    conversion.ip = click.ip
    conversion.ua = click.ua
    conversion.country = click.country

    conversion.goal_value = data['goal']
    conversion.sum = data['sum']
    conversion.txid = txid

    conversion.save()
    return conversion
