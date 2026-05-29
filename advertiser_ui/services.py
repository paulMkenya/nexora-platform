"""
Dashboard query and cache layer for the advertiser portal.

All data is scoped to offers owned by the given Advertiser instance —
no cross-advertiser leakage is possible at the query level.
"""
from datetime import timedelta
from decimal import Decimal

from django.core.cache import cache
from django.db.models import Count, Sum
from django.utils import timezone

from offer.models import Offer
from tracker.models import APPROVED_STATUS, Click, Conversion

CACHE_TTL = 60  # seconds


# ── helpers ────────────────────────────────────────────────────────────────

def _today_start():
    return timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)


def _rolling_start(days):
    return timezone.now() - timedelta(days=days)


def _offer_qs(advertiser):
    """Lazy queryset used as an IN subquery — never materialised in Python."""
    return Offer.objects.filter(advertiser=advertiser).values('id')


# ── period stats ───────────────────────────────────────────────────────────

def _stats_for_period(offer_ids, since):
    """
    Return a single dict with clicks, conversions, cr, payout for one window.
    Executes 3 aggregation queries; all scoped via the offer_ids subquery.
    """
    clicks = Click.objects.filter(
        offer_id__in=offer_ids,
        created_at__gte=since,
    ).count()

    convs_qs = Conversion.objects.filter(
        offer_id__in=offer_ids,
        created_at__gte=since,
    )
    total_convs = convs_qs.count()

    payout = (
        convs_qs.filter(status=APPROVED_STATUS)
        .aggregate(total=Sum('payout'))['total']
        or Decimal('0.00')
    )

    cr = round(total_convs / clicks * 100, 2) if clicks else 0.0

    return {
        'clicks': clicks,
        'conversions': total_convs,
        'cr': cr,
        'payout': payout,
    }


# ── top offers ─────────────────────────────────────────────────────────────

def _top_offers(offer_ids, limit=5):
    """
    Single annotated query: JOINs Conversion → Offer, groups, sums revenue.
    No N+1 — one round-trip to Postgres.
    """
    return list(
        Conversion.objects.filter(
            offer_id__in=offer_ids,
            status=APPROVED_STATUS,
        )
        .values('offer_id', 'offer__title')
        .annotate(
            revenue=Sum('revenue'),
            conversions=Count('id'),
        )
        .order_by('-revenue')[:limit]
    )


# ── public API ─────────────────────────────────────────────────────────────

def get_dashboard_data(advertiser):
    """
    Return cached dashboard payload for *advertiser*.

    Cache key is per-advertiser, TTL = CACHE_TTL seconds.
    All values in the returned dict are plain Python types (safe to pickle).
    """
    cache_key = f'adv_dashboard_{advertiser.pk}'
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    offer_ids = _offer_qs(advertiser)

    data = {
        'today':   _stats_for_period(offer_ids, _today_start()),
        'last_7':  _stats_for_period(offer_ids, _rolling_start(7)),
        'last_30': _stats_for_period(offer_ids, _rolling_start(30)),
        'top_offers': _top_offers(offer_ids),
    }

    cache.set(cache_key, data, CACHE_TTL)
    return data
