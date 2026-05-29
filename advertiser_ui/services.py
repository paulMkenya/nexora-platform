"""
Dashboard query and cache layer for the advertiser portal.

All data is scoped to offers owned by the given Advertiser instance —
no cross-advertiser leakage is possible at the query level.
"""
from datetime import timedelta
from decimal import Decimal

from django.core.cache import cache
from django.db.models import Count, DecimalField, IntegerField, OuterRef, Subquery, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from offer.models import Offer, Payout
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


# ── offers list ────────────────────────────────────────────────────────────

def get_offers_list(advertiser, status_filter=''):
    """
    Return all of the advertiser's offers annotated with 30-day stats.

    Uses four correlated subqueries (clicks, conversions, revenue, best_payout)
    so that multiple aggregate columns cannot inflate each other via JOIN
    multiplication. prefetch_related handles the countries M2M in one extra
    query — total is 2 DB round-trips regardless of offer count.
    """
    since = _rolling_start(30)

    clicks_sq = (
        Click.objects
        .filter(offer_id=OuterRef('pk'), created_at__gte=since)
        .values('offer_id')
        .annotate(n=Count('pk'))
        .values('n')
    )
    conversions_sq = (
        Conversion.objects
        .filter(offer_id=OuterRef('pk'), created_at__gte=since)
        .values('offer_id')
        .annotate(n=Count('pk'))
        .values('n')
    )
    revenue_sq = (
        Conversion.objects
        .filter(offer_id=OuterRef('pk'), created_at__gte=since, status=APPROVED_STATUS)
        .values('offer_id')
        .annotate(s=Sum('revenue'))
        .values('s')
    )
    best_payout_sq = (
        Payout.objects
        .filter(offer_id=OuterRef('pk'))
        .order_by('-payout')
        .values('payout')[:1]
    )

    qs = (
        Offer.objects
        .filter(advertiser=advertiser)
        .prefetch_related('countries')
        .annotate(
            clicks_30d=Coalesce(
                Subquery(clicks_sq, output_field=IntegerField()), 0),
            conversions_30d=Coalesce(
                Subquery(conversions_sq, output_field=IntegerField()), 0),
            revenue_30d=Coalesce(
                Subquery(revenue_sq, output_field=DecimalField(max_digits=10, decimal_places=2)),
                Decimal('0.00'),
            ),
            best_payout=Subquery(
                best_payout_sq, output_field=DecimalField(max_digits=7, decimal_places=2)),
        )
        .order_by('-id')
    )

    if status_filter:
        qs = qs.filter(status=status_filter)

    return list(qs)
