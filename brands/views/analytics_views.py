"""Operator Analytics Overview — /admin/analytics/.

WHY THIS DOES NOT USE reporting/backends
----------------------------------------
``reporting`` exists for the *public API* at scale: it reads Postgres
materialized views refreshed every five minutes by a Celery beat task, and its
interface (``revenue_report(brand_id, ...) -> ReportPage``) is per-brand and
paged. Two things make it the wrong source for this page:

1. **Freshness.** An operator lands here from the Dashboard, which counts
   clicks and conversions live. Reading a five-minute-old matview would show a
   different "total conversions" than the page they just left, and the obvious
   conclusion is that one of them is broken.
2. **Scope.** A platform owner sees every brand at once. The backend takes a
   single ``brand_id``; an all-brands view would mean looping brands and
   re-summing in Python, which is both slower and a second place for the
   aggregation to drift.

So this aggregates the source tables directly, exactly as the operator
Dashboard and the fraud console do. If this page ever needs to span months
rather than a 30-day window, that is the point to revisit — not before.
"""
import datetime

from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Avg, Count, Sum
from django.db.models.functions import TruncDate
from django.shortcuts import render
from django.utils import timezone

from brands.scoping import scope_brand, sees_all_brands
from nexora import charts

WINDOW_DAYS = 30
WINDOW_CHOICES = (7, 30, 90)


@staff_member_required
def analytics(request):
    show_all_brands = sees_all_brands(request.user)
    brand = scope_brand(request)

    try:
        days = int(request.GET.get('days', WINDOW_DAYS))
    except (TypeError, ValueError):
        days = WINDOW_DAYS
    if days not in WINDOW_CHOICES:
        days = WINDOW_DAYS

    from tracker.models import Click, Conversion, APPROVED_STATUS

    now = timezone.now()
    start = (now - datetime.timedelta(days=days - 1)).date()
    # The immediately preceding window of the same length, for the deltas.
    prev_start = start - datetime.timedelta(days=days)

    clicks = Click.objects.all()
    conversions = Conversion.objects.all()
    if not show_all_brands:
        clicks = clicks.filter(brand=brand)
        conversions = conversions.filter(brand=brand)

    current = _totals(clicks, conversions, start, None, APPROVED_STATUS)
    previous = _totals(clicks, conversions, prev_start, start, APPROVED_STATUS)

    daily_clicks = _daily(clicks, start)
    daily_convs = _daily(conversions, start)
    labels, click_series, conv_series = _align(daily_clicks, daily_convs, start, days)

    return render(request, 'admin_shared/analytics.html', {
        'active': 'analytics',
        'shell_role': 'admin',
        'page_title': 'Analytics',
        'show_all_brands': show_all_brands,
        'brand': brand,
        'days': days,
        'window_choices': WINDOW_CHOICES,
        'totals': current,
        'deltas': {
            'clicks': _delta(current['clicks'], previous['clicks']),
            'conversions': _delta(current['conversions'], previous['conversions']),
            'revenue': _delta(current['revenue'], previous['revenue']),
            'conversion_rate': _delta(current['conversion_rate'], previous['conversion_rate']),
        },
        'sparks': {
            'clicks': charts.sparkline(click_series),
            'conversions': charts.sparkline(conv_series),
        },
        'trend': charts.area_chart(
            [
                {'label': 'Clicks', 'values': click_series},
                {'label': 'Conversions', 'values': conv_series},
            ],
            labels,
        ),
        'traffic_mix': _traffic_mix(clicks, start),
        'top_offers': _top_offers(clicks, conversions, start, APPROVED_STATUS),
    })


def _totals(clicks, conversions, start, end, approved_status):
    """Headline figures for one window. ``end`` of None means "up to now"."""
    click_qs = clicks.filter(created_at__date__gte=start)
    conv_qs = conversions.filter(created_at__date__gte=start)
    if end is not None:
        click_qs = click_qs.filter(created_at__date__lt=end)
        conv_qs = conv_qs.filter(created_at__date__lt=end)

    click_count = click_qs.count()
    conv_count = conv_qs.count()
    approved = conv_qs.filter(status=approved_status)

    revenue = approved.aggregate(t=Sum('payout'))['t'] or 0
    avg_payout = approved.aggregate(a=Avg('payout'))['a'] or 0

    return {
        'clicks': click_count,
        'conversions': conv_count,
        # Conversion rate is conversions per click. With no clicks it is
        # undefined, not zero — but zero is what a rate is displayed as, and
        # the tile beside it shows the click count, so the reader can tell the
        # difference between "nobody converted" and "nobody arrived".
        'conversion_rate': (conv_count / click_count * 100) if click_count else 0,
        'revenue': revenue,
        'avg_payout': avg_payout,
    }


def _delta(current, previous):
    """Percent change against the previous window.

    Returns None when there is no baseline: "up 100%" from a base of zero is
    meaningless, and rendering it as a green arrow overstates a single event.
    """
    if not previous:
        return None
    return round((float(current) - float(previous)) / float(previous) * 100, 1)


def _daily(qs, start):
    rows = (
        qs.filter(created_at__date__gte=start)
        .annotate(day=TruncDate('created_at'))
        .values('day')
        .annotate(n=Count('id'))
    )
    return {row['day']: row['n'] for row in rows}


def _align(daily_a, daily_b, start, days):
    """One point per day across the window, zero-filled.

    Dropping empty days would compress the x-axis and make an intermittent
    pattern look continuous — and would also desynchronise the two series,
    since they rarely go quiet on the same days.
    """
    labels, series_a, series_b = [], [], []
    for offset in range(days):
        day = start + datetime.timedelta(days=offset)
        labels.append(day.strftime('%b %d'))
        series_a.append(daily_a.get(day, 0))
        series_b.append(daily_b.get(day, 0))
    return labels, series_a, series_b


def _traffic_mix(clicks, start, *, limit=5):
    """Click share by traffic source, with a real "Other" bucket.

    Traffic source is ``Click.sub1``. That is not an arbitrary choice — it is
    the same derivation the reporting matviews use (``sub1 AS traffic_source``
    in reporting/migrations/0001_reporting_matviews.py), so this page and the
    public API agree on what the phrase means. Note it is deliberately NOT
    ``Offer.traffic_sources``: that is a many-to-many, and grouping clicks
    through it would count one click once per source the offer is tagged with.

    Anything past the top few folds into Other rather than being given its own
    hue — a categorical palette has a fixed number of slots and the rule is not
    to invent a seventh.
    """
    rows = list(
        clicks.filter(created_at__date__gte=start)
        .values('sub1')
        .annotate(n=Count('id'))
        .order_by('-n')
    )
    if not rows:
        return charts.donut([])

    segments = [(row['sub1'] or 'Unattributed', row['n']) for row in rows[:limit]]
    tail = sum(row['n'] for row in rows[limit:])
    if tail:
        segments.append(('Other', tail, 'muted'))
    return charts.donut(segments)


def _top_offers(clicks, conversions, start, approved_status, *, limit=5):
    """Offers ranked by approved revenue, each as a share of the leader."""
    rows = list(
        conversions.filter(created_at__date__gte=start, status=approved_status)
        .values('offer_id', 'offer__title')
        .annotate(revenue=Sum('payout'), n=Count('id'))
        .order_by('-revenue')[:limit]
    )
    if not rows:
        return []

    click_counts = {
        row['offer_id']: row['n']
        for row in clicks.filter(created_at__date__gte=start)
        .values('offer_id').annotate(n=Count('id'))
    }

    top_revenue = rows[0]['revenue'] or 1
    out = []
    for row in rows:
        offer_clicks = click_counts.get(row['offer_id'], 0)
        revenue = row['revenue'] or 0
        out.append({
            'name': row['offer__title'] or 'Unattributed',
            'revenue': revenue,
            # Built here, not with {{ "$"|add:revenue }} — Django's `add`
            # filter returns '' when it cannot coerce both sides, so string +
            # Decimal silently blanks the label.
            'revenue_display': f'${revenue:.2f}',
            'conversions': row['n'],
            'clicks': offer_clicks,
            'epc': (float(revenue) / offer_clicks) if offer_clicks else 0,
            'share': charts.meter(revenue, top_revenue),
        })
    return out
