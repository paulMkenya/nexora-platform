import csv

from django.contrib import messages
from django.contrib.auth import logout
from django.core.exceptions import ObjectDoesNotExist
from django.db.models import Count
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from offer.models import Offer

from advertiser.decorators import advertiser_required
from advertiser_ui.services import (
    CONVERSION_STATUSES,
    bulk_update_conversions,
    get_conversions_for_export,
    get_conversions_page,
    get_dashboard_data,
    get_offers_list,
    parse_conversion_filters,
)


# ── helpers ────────────────────────────────────────────────────────────────

def _get_advertiser(request):
    try:
        return request.user.advertiser_profile
    except ObjectDoesNotExist:
        return None


def _filter_qs_string(request):
    """Reconstruct filter query string from GET params for post-action redirect."""
    keep = ('offer_id', 'status', 'date_from', 'date_to', 'sub1', 'sub2', 'sub3', 'sub4', 'sub5', 'page')
    parts = [(k, v) for k, v in request.GET.items() if k in keep and v]
    if not parts:
        return ''
    from urllib.parse import urlencode
    return '?' + urlencode(parts)


# ── dashboard ──────────────────────────────────────────────────────────────

@advertiser_required
def dashboard(request):
    advertiser = _get_advertiser(request)
    if not advertiser:
        return render(request, 'advertiser_ui/dashboard.html', {'no_account': True})

    data = get_dashboard_data(advertiser)
    ctx = {
        **data,
        'period_rows': [
            ('Today',        data['today']),
            ('Last 7 days',  data['last_7']),
            ('Last 30 days', data['last_30']),
        ],
    }
    return render(request, 'advertiser_ui/dashboard.html', ctx)


# ── offers ─────────────────────────────────────────────────────────────────

@advertiser_required
def offers(request):
    advertiser = _get_advertiser(request)
    if not advertiser:
        return render(request, 'advertiser_ui/offers.html', {'no_account': True})

    status_filter = request.GET.get('status', '')
    offer_list = get_offers_list(advertiser, status_filter=status_filter)

    status_counts = dict(
        Offer.objects
        .filter(advertiser=advertiser)
        .values_list('status')
        .annotate(n=Count('id'))
    )

    return render(request, 'advertiser_ui/offers.html', {
        'offers': offer_list,
        'status_filter': status_filter,
        'status_counts': status_counts,
        'total_count': sum(status_counts.values()),
    })


# ── conversions ────────────────────────────────────────────────────────────

@advertiser_required
def conversions(request):
    advertiser = _get_advertiser(request)
    if not advertiser:
        return render(request, 'advertiser_ui/conversions.html', {'no_account': True})

    filters = parse_conversion_filters(request.GET)
    page_obj = get_conversions_page(advertiser, filters, page=request.GET.get('page', 1))
    offer_list = Offer.objects.filter(advertiser=advertiser).only('id', 'title').order_by('title')

    return render(request, 'advertiser_ui/conversions.html', {
        'page_obj':    page_obj,
        'filters':     filters,
        'offers':      offer_list,
        'status_choices': CONVERSION_STATUSES,
    })


@require_POST
@advertiser_required
def bulk_action(request):
    advertiser = _get_advertiser(request)
    if not advertiser:
        return HttpResponseForbidden()

    action  = request.POST.get('action', '').strip()
    reason  = request.POST.get('reason', '').strip()
    raw_ids = request.POST.getlist('ids')

    if not raw_ids:
        messages.warning(request, 'No rows selected.')
        return redirect('advertiser_ui:conversions')

    if action not in ('approve', 'reject', 'hold'):
        messages.error(request, 'Unknown action.')
        return redirect('advertiser_ui:conversions')

    updated, skipped = bulk_update_conversions(advertiser, raw_ids, action, reason)

    label = {'approve': 'approved', 'reject': 'rejected', 'hold': 'held'}[action]
    if updated:
        messages.success(request, f'{updated} conversion(s) {label}.')
    if skipped:
        messages.warning(request, f'{skipped} row(s) skipped (not authorised).')

    return redirect('advertiser_ui:conversions' + _filter_qs_string(request))


@advertiser_required
def export_csv(request):
    advertiser = _get_advertiser(request)
    if not advertiser:
        return HttpResponseForbidden()

    filters = parse_conversion_filters(request.GET)
    rows = get_conversions_for_export(advertiser, filters)

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="conversions.csv"'

    writer = csv.writer(response)
    writer.writerow([
        'ID', 'Date (UTC)', 'Offer', 'Affiliate', 'Status',
        'Payout', 'Revenue', 'Sub1', 'Sub2', 'Sub3', 'Sub4', 'Sub5',
        'Click ID', 'Goal', 'Comment',
    ])
    for c in rows:
        writer.writerow([
            str(c.id),
            c.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            c.offer.title if c.offer else '',
            c.affiliate.username if c.affiliate else '',
            c.status,
            str(c.payout),
            str(c.revenue),
            c.sub1, c.sub2, c.sub3, c.sub4, c.sub5,
            str(c.click_id or ''),
            c.goal_value,
            c.comment,
        ])

    return response


# ── stubs ──────────────────────────────────────────────────────────────────

@advertiser_required
def postbacks(request):
    return render(request, 'advertiser_ui/postbacks.html')


@advertiser_required
def wallet(request):
    return render(request, 'advertiser_ui/wallet.html')


@advertiser_required
def settings_view(request):
    return render(request, 'advertiser_ui/settings.html')


def advertiser_logout(request):
    logout(request)
    return redirect('affiliate_ui:login')
