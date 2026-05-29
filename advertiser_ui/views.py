from django.contrib.auth import logout
from django.core.exceptions import ObjectDoesNotExist
from django.db.models import Count
from django.shortcuts import redirect, render

from offer.models import Offer

from advertiser.decorators import advertiser_required
from advertiser_ui.services import get_dashboard_data, get_offers_list


@advertiser_required
def dashboard(request):
    try:
        advertiser = request.user.advertiser_profile
    except ObjectDoesNotExist:
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


@advertiser_required
def offers(request):
    try:
        advertiser = request.user.advertiser_profile
    except ObjectDoesNotExist:
        return render(request, 'advertiser_ui/offers.html', {'no_account': True})

    status_filter = request.GET.get('status', '')
    offer_list = get_offers_list(advertiser, status_filter=status_filter)

    # Status counts for filter pills — one aggregation query.
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


@advertiser_required
def conversions(request):
    return render(request, 'advertiser_ui/conversions.html')


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
