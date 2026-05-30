import logging

import redis as _redis

from django.conf import settings

from project._celery import _celery
from project.redis_conn import pool

logger = logging.getLogger(__name__)

FLOOD_WINDOW = 60   # seconds
FLOOD_KEY_TTL = 120


def _flood_count(ip: str) -> int:
    """Increment and return the 60-second click count for this IP."""
    try:
        r = _redis.Redis(connection_pool=pool)
        key = f'fraud:flood:{ip}'
        pipe = r.pipeline()
        pipe.incr(key)
        pipe.expire(key, FLOOD_KEY_TTL)
        count, _ = pipe.execute()
        return int(count)
    except Exception:
        return 0


def _repeat_click(ip: str, offer_id) -> bool:
    """True if this IP already clicked this offer in the past 24 h."""
    try:
        r = _redis.Redis(connection_pool=pool)
        key = f'fraud:repeat:{ip}:{offer_id}'
        already = r.exists(key)
        r.set(key, 1, ex=86400)
        return bool(already)
    except Exception:
        return False


@_celery.task(bind=True, max_retries=2)
def score_click_fraud(self, click_id: str):
    """Compute fraud score for a click and persist to DB."""
    from tracker.models import Click
    from fraud.rules import score_click

    try:
        click = Click.objects.select_related('offer').get(pk=click_id)
    except Click.DoesNotExist:
        logger.warning('score_click_fraud: click %s not found', click_id)
        return

    # Build context
    offer_countries = []
    if click.offer:
        offer_countries = list(
            click.offer.countries.values_list('iso', flat=True)
        )

    flood_count = _flood_count(click.ip or '')
    repeat = _repeat_click(click.ip or '', click.offer_id)

    ctx = {
        'ua': click.ua,
        'ip': click.ip,
        'country': click.country,
        'offer_countries': offer_countries,
        'referrer': '',          # not captured at click time
        'click_flood_count': flood_count,
        'repeat_click': repeat,
    }

    score, reasons = score_click(ctx)

    threshold = getattr(settings, 'FRAUD_AUTO_REJECT_AT', 70)
    is_bot = any(r.startswith('bot_ua') for r in reasons)

    # Optional IPQS enrichment (no-op when IPQS_API_KEY is blank)
    from fraud.ipqs import enrich_click
    enrich_click(click_id)

    # Re-fetch to pick up any IPQS updates before final write
    click.refresh_from_db(fields=['is_proxy', 'is_datacenter', 'is_bot'])
    if click.is_bot:
        is_bot = True

    Click.objects.filter(pk=click_id).update(
        fraud_score=score,
        fraud_reasons=reasons,
        is_bot=is_bot,
    )

    if score >= threshold:
        logger.info('click %s auto-rejected fraud_score=%d reasons=%s', click_id, score, reasons)

    return f'click {click_id} fraud_score={score}'


@_celery.task(bind=True, max_retries=2)
def score_conversion_fraud(self, conversion_id: str):
    """Compute fraud score for a conversion and auto-reject if above threshold."""
    from tracker.models import Conversion, REJECTED_STATUS
    from fraud.conversion_rules import score_conversion
    from django.db.models import Avg
    from django.utils import timezone
    import datetime

    try:
        conv = Conversion.objects.select_related('offer').get(pk=conversion_id)
    except Conversion.DoesNotExist:
        logger.warning('score_conversion_fraud: conversion %s not found', conversion_id)
        return

    # click-to-conversion seconds
    c2c_secs = None
    if conv.click_date and conv.created_at:
        delta = conv.created_at - conv.click_date
        c2c_secs = delta.total_seconds()

    # conversion velocity — same affiliate+offer in last hour
    one_hour_ago = timezone.now() - datetime.timedelta(hours=1)
    velocity = Conversion.objects.filter(
        affiliate_id=conv.affiliate_id,
        offer_id=conv.offer_id,
        created_at__gte=one_hour_ago,
    ).count()

    # avg payout for this offer
    avg_row = Conversion.objects.filter(
        offer_id=conv.offer_id,
        payout__gt=0,
    ).aggregate(avg=Avg('payout'))
    avg_payout = float(avg_row['avg'] or 0)

    ctx = {
        'click_to_conversion_seconds': c2c_secs,
        'conversion_velocity': velocity,
        'payout': float(conv.payout),
        'avg_payout': avg_payout,
    }

    score, reasons = score_conversion(ctx)

    threshold = getattr(settings, 'FRAUD_AUTO_REJECT_AT', 70)
    update_fields = {'fraud_score': score, 'fraud_reasons': reasons}

    if score >= threshold and conv.status not in (REJECTED_STATUS,):
        update_fields['status'] = REJECTED_STATUS
        update_fields['auto_rejected_reason'] = '; '.join(reasons)
        logger.info('conversion %s auto-rejected fraud_score=%d', conversion_id, score)
    elif reasons:
        update_fields['auto_rejected_reason'] = '; '.join(reasons)

    Conversion.objects.filter(pk=conversion_id).update(**update_fields)
    return f'conversion {conversion_id} fraud_score={score}'
