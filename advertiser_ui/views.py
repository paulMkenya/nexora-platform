from django.contrib.auth import logout
from django.shortcuts import redirect, render

from advertiser.decorators import advertiser_required


@advertiser_required
def dashboard(request):
    return render(request, 'advertiser_ui/dashboard.html')


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
