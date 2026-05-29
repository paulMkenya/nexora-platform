from django.contrib.auth import logout
from django.core.exceptions import ObjectDoesNotExist
from django.shortcuts import redirect, render

from advertiser.decorators import advertiser_required
from advertiser_ui.services import get_dashboard_data


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
    return render(request, 'advertiser_ui/offers.html')


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
