"""
Dashboard query and cache layer for the advertiser portal.

All data is scoped to offers owned by the given Advertiser instance —
no cross-advertiser leakage is possible at the query level.
"""
import uuid
from datetime import date, timedelta
from decimal import Decimal

from django.core.cache import cache
from django.core.paginator import Paginator
from django.db.models import Count, DecimalField, IntegerField, OuterRef, Subquery, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from offer.models import Offer, Payout
from postback.tasks.send_postback import send_postback as _send_postback
from tracker.models import APPROVED_STATUS, HOLD_STATUS, REJECTED_STATUS, Click, Conversion

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


# ── conversions list + filter ──────────────────────────────────────────────

CONVERSION_STATUSES = [
    ('', 'All statuses'),
    (APPROVED_STATUS, 'Approved'),
    (HOLD_STATUS,     'Hold'),
    (REJECTED_STATUS, 'Rejected'),
    ('pending',       'Pending'),
]

PER_PAGE = 50


def parse_conversion_filters(GET):
    """
    Extract and normalise filter values from a GET QueryDict.
    date_from / date_to default to last 7 days when absent from the request.
    """
    today = date.today()
    return {
        'offer_id':  GET.get('offer_id', '').strip(),
        'status':    GET.get('status', '').strip(),
        'date_from': GET.get('date_from', '').strip() or (today - timedelta(days=7)).isoformat(),
        'date_to':   GET.get('date_to', '').strip() or today.isoformat(),
        'sub1': GET.get('sub1', '').strip(),
        'sub2': GET.get('sub2', '').strip(),
        'sub3': GET.get('sub3', '').strip(),
        'sub4': GET.get('sub4', '').strip(),
        'sub5': GET.get('sub5', '').strip(),
    }


def _build_conversions_qs(advertiser, filters):
    """
    Return a filtered Conversion queryset scoped to *advertiser*.
    Does not paginate — callers choose between pagination and full export.
    """
    qs = (
        Conversion.objects
        .filter(offer_id__in=_offer_qs(advertiser))
        .select_related('offer', 'affiliate', 'currency')
        .order_by('-created_at')
    )

    if filters.get('offer_id'):
        try:
            qs = qs.filter(offer_id=int(filters['offer_id']))
        except (ValueError, TypeError):
            pass

    if filters.get('status'):
        qs = qs.filter(status=filters['status'])

    if filters.get('date_from'):
        try:
            qs = qs.filter(created_at__date__gte=filters['date_from'])
        except Exception:
            pass

    if filters.get('date_to'):
        try:
            qs = qs.filter(created_at__date__lte=filters['date_to'])
        except Exception:
            pass

    for i in range(1, 6):
        v = filters.get(f'sub{i}', '')
        if v:
            qs = qs.filter(**{f'sub{i}__icontains': v})

    return qs


def get_conversions_page(advertiser, filters, page=1):
    qs = _build_conversions_qs(advertiser, filters)
    return Paginator(qs, PER_PAGE).get_page(page)


def get_conversions_for_export(advertiser, filters):
    return _build_conversions_qs(advertiser, filters).iterator()


# ── bulk status update ─────────────────────────────────────────────────────

_ACTION_STATUS = {
    'approve': APPROVED_STATUS,
    'reject':  REJECTED_STATUS,
    'hold':    HOLD_STATUS,
}


def bulk_update_conversions(advertiser, raw_ids, action, reason=''):
    """
    Update conversion statuses and fire outbound postbacks.

    Only conversions whose offer.advertiser == *advertiser* are touched;
    any foreign IDs in *raw_ids* are silently excluded (counted as skipped).

    Returns (updated_count, skipped_count).
    """
    new_status = _ACTION_STATUS.get(action)
    if not new_status:
        raise ValueError(f'Unknown action: {action!r}')

    # Validate and normalise UUIDs — malformed values are dropped
    valid_ids = []
    for raw in raw_ids:
        try:
            valid_ids.append(uuid.UUID(str(raw)))
        except (ValueError, AttributeError):
            pass

    if not valid_ids:
        return 0, len(raw_ids)

    # Scope strictly to this advertiser's offers
    safe_qs = Conversion.objects.filter(
        pk__in=valid_ids,
        offer_id__in=_offer_qs(advertiser),
    )

    authorised_ids = list(safe_qs.values_list('pk', flat=True))
    skipped = len(valid_ids) - len(authorised_ids)

    if not authorised_ids:
        return 0, skipped

    update_fields = {'status': new_status}
    if reason:
        update_fields['comment'] = reason

    safe_qs.update(**update_fields)

    # bulk .update() bypasses post_save signal, so fire postbacks explicitly
    for conv in (
        Conversion.objects
        .filter(pk__in=authorised_ids)
        .select_related('currency')
    ):
        if conv.affiliate_id and conv.offer_id:
            _send_postback.delay({
                'affiliate_id': conv.affiliate_id,
                'offer_id':     conv.offer_id,
                'sub1': conv.sub1, 'sub2': conv.sub2,
                'sub3': conv.sub3, 'sub4': conv.sub4,
                'sub5': conv.sub5,
                'payout':     str(conv.payout),
                'goal_value': conv.goal_value,
                'currency':   conv.currency.code if conv.currency else '',
            })

    return len(authorised_ids), skipped
