import datetime
import logging

from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Count, Avg
from django.shortcuts import render, redirect
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from brands.scoping import scope_brand, sees_all_brands
from fraud.models import FraudWhitelist
from tracker.models import Click, Conversion, REJECTED_STATUS

logger = logging.getLogger(__name__)


def _last_24h():
    return timezone.now() - datetime.timedelta(hours=24)


@staff_member_required
def dashboard(request):
    since = _last_24h()

    # Fraud signals live on clicks/conversions, which carry a brand. Brand-scoped
    # operators see only their own brand; superusers see every brand and any
    # orphaned (brand-less) records.
    show_all_brands = sees_all_brands(request.user)
    clicks = Click.objects.all()
    conversions = Conversion.objects.all()
    if not show_all_brands:
        brand = scope_brand(request)
        clicks = clicks.filter(brand=brand)
        conversions = conversions.filter(brand=brand)
    elif Click.objects.filter(brand__isnull=True, fraud_score__gt=0).exists():
        logger.warning('fraud dashboard: brand-less flagged clicks present (shown to superuser only)')

    # Flagged clicks (fraud_score > 0) in last 24 h
    flagged_clicks = (
        clicks
        .filter(created_at__gte=since, fraud_score__gt=0)
        .select_related('offer', 'affiliate')
        .order_by('-fraud_score')[:50]
    )

    # Auto-rejected conversions in last 24 h
    flagged_conversions = (
        conversions
        .filter(created_at__gte=since, fraud_score__gt=0)
        .select_related('offer', 'affiliate')
        .order_by('-fraud_score')[:50]
    )

    # Top offending IPs (by flagged click count)
    top_ips = (
        clicks
        .filter(created_at__gte=since, fraud_score__gt=0)
        .values('ip')
        .annotate(count=Count('id'), avg_score=Avg('fraud_score'))
        .order_by('-count')[:10]
    )

    # Aggregate reason counts from JSON field
    all_clicks_24h = clicks.filter(created_at__gte=since, fraud_score__gt=0)
    reason_counts: dict = {}
    for c in all_clicks_24h.values_list('fraud_reasons', flat=True):
        for reason in (c or []):
            tag = reason.split(':')[0] if ':' in reason else reason
            reason_counts[tag] = reason_counts.get(tag, 0) + 1
    top_reasons = sorted(reason_counts.items(), key=lambda x: x[1], reverse=True)[:8]

    # Summary stats
    total_clicks_24h = clicks.filter(created_at__gte=since).count()
    total_flagged_clicks = all_clicks_24h.count()
    total_flagged_convs = conversions.filter(
        created_at__gte=since, fraud_score__gt=0,
    ).count()
    auto_rejected = conversions.filter(
        created_at__gte=since,
        status=REJECTED_STATUS,
        auto_rejected_reason__gt='',
    ).count()

    whitelist = FraudWhitelist.objects.all()

    ctx = {
        'flagged_clicks': flagged_clicks,
        'flagged_conversions': flagged_conversions,
        'top_ips': top_ips,
        'top_reasons': top_reasons,
        'total_clicks_24h': total_clicks_24h,
        'total_flagged_clicks': total_flagged_clicks,
        'total_flagged_convs': total_flagged_convs,
        'auto_rejected': auto_rejected,
        'whitelist': whitelist,
        'show_all_brands': show_all_brands,
    }
    return render(request, 'fraud/dashboard.html', ctx)


@staff_member_required
@require_http_methods(['POST'])
def whitelist_add(request):
    entry_type = request.POST.get('entry_type', '').strip()
    value = request.POST.get('value', '').strip()
    note = request.POST.get('note', '').strip()
    if entry_type in ('ip', 'pid') and value:
        FraudWhitelist.objects.get_or_create(
            value=value,
            defaults={'entry_type': entry_type, 'note': note, 'created_by': request.user},
        )
    return redirect('fraud:dashboard')


@staff_member_required
@require_http_methods(['POST'])
def whitelist_remove(request, pk: int):
    FraudWhitelist.objects.filter(pk=pk).delete()
    return redirect('fraud:dashboard')
