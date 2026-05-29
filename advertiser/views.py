from django.shortcuts import render

from .decorators import advertiser_required


@advertiser_required
def dashboard(request):
    return render(request, 'advertiser/dashboard.html')
