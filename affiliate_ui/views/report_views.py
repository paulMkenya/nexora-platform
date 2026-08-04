import iso8601
from datetime import datetime, time, timedelta, date
from django.db.models import Q
from django.shortcuts import render

from affiliate_ui.gates import require_approved_affiliate
from affiliate_ui.views.general_views import offers_for_affiliate
from affiliate.dao import daily_report, offer_report, goal_report


@require_approved_affiliate
def daily_report_view(request):
    start_date_arg = request.GET.get('start_date')
    end_date_arg = request.GET.get('end_date')
    offer_id = request.GET.get('offer_id')

    if start_date_arg:
        start_date = iso8601.parse_date(start_date_arg).date()
    else:
        start_date = date.today() - timedelta(days=6)

    if end_date_arg:
        end_date = iso8601.parse_date(end_date_arg).date()
    else:
        end_date = date.today()

    start_datetime = datetime.combine(start_date, time.min)
    end_datetime = datetime.combine(end_date, time.max)

    if start_datetime <= end_datetime:
        data = daily_report(
            request.user.id, start_datetime, end_datetime, int(offer_id) if offer_id else 0)
    else:
        data = []

    # Offers this affiliate has actually driven traffic to. Keyed off clicks
    # OR conversions: keying off conversions alone made the filter unusable
    # for anyone who has sent traffic but not yet converted — which is every
    # affiliate on day one, i.e. exactly when they go looking for the filter.
    #
    # Intersected with offers_for_affiliate so the filter obeys the same
    # brand-only rule as every other surface: historical traffic to an offer
    # that is no longer theirs (or was never branded to them) must not put
    # another brand's offer title in this dropdown.
    #
    # historical=True because this is the one backward-looking surface: an
    # offer whose advertiser was later suspended or archived must still be
    # filterable by the affiliate who already drove traffic to it. Brand
    # isolation is unaffected — only the availability gate is relaxed.
    offers = offers_for_affiliate(request.user, historical=True).filter(
        Q(conversions__affiliate=request.user) | Q(clicks__affiliate=request.user)
    ).distinct()

    context = {
        'data': data,
        'offers': offers,
        'selected_offer_id': int(offer_id) if offer_id else None,
        'start_date': start_date.isoformat(),
        'end_date': end_date.isoformat(),
    }
    return render(request, 'affiliate_ui/daily_report.html', context)


@require_approved_affiliate
def offer_report_view(request):
    start_date_arg = request.GET.get('start_date')
    end_date_arg = request.GET.get('end_date')

    if start_date_arg:
        start_date = iso8601.parse_date(start_date_arg).date()
    else:
        start_date = date.today() - timedelta(days=6)

    if end_date_arg:
        end_date = iso8601.parse_date(end_date_arg).date()
    else:
        end_date = date.today()

    start_datetime = datetime.combine(start_date, time.min)
    end_datetime = datetime.combine(end_date, time.max)

    if start_datetime <= end_datetime:
        data = offer_report(request.user.id, start_datetime, end_datetime)
    else:
        data = []

    context = {
        'data': data,
        'start_date': start_date.isoformat(),
        'end_date': end_date.isoformat(),
    }
    return render(request, 'affiliate_ui/offer_report.html', context)


@require_approved_affiliate
def goal_report_view(request):
    start_date_arg = request.GET.get('start_date')
    end_date_arg = request.GET.get('end_date')

    if start_date_arg:
        start_date = iso8601.parse_date(start_date_arg).date()
    else:
        start_date = date.today() - timedelta(days=6)

    if end_date_arg:
        end_date = iso8601.parse_date(end_date_arg).date()
    else:
        end_date = date.today()

    start_datetime = datetime.combine(start_date, time.min)
    end_datetime = datetime.combine(end_date, time.max)

    data = goal_report(request.user.id, start_datetime, end_datetime)

    context = {
        'data': data,
        'start_date': start_date.isoformat(),
        'end_date': end_date.isoformat(),
    }
    return render(request, 'affiliate_ui/goal_report.html', context)
