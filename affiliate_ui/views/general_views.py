from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.contrib.auth import logout as auth_logout
from django.contrib.auth.decorators import login_required
from django.db.models import Q, Sum, Prefetch
from django.shortcuts import redirect, render, get_object_or_404
from django.contrib.auth.views import LoginView
from django.views.decorators.http import require_POST

from affiliate_ui.gates import require_approved_affiliate
from offer.models import Advertiser, Offer, Category, Payout, TrafficSource, ACTIVE_STATUS, revenue_models
from user_profile.geo import country_choices
from tracker.models import Click, Conversion, APPROVED_STATUS
from user_profile.models import Profile


@login_required
def dashboard(request):
    clicks_count = Click.objects.filter(affiliate=request.user).count()

    conversions = Conversion.objects.filter(affiliate=request.user)
    conversions_count = conversions.count()

    total_earnings = conversions.filter(
        status=APPROVED_STATUS).aggregate(total=Sum('payout'))['total'] or 0

    try:
        profile = request.user.profile
        is_pending = (
            profile.role == Profile.Role.AFFILIATE
            and (
                profile.affiliate_status != Profile.AffiliateStatus.APPROVED
                or not profile.email_verified
            )
        )
    except Exception:
        is_pending = False

    context = {
        'clicks_count': clicks_count,
        'conversions_count': conversions_count,
        'total_earnings': f'{total_earnings:.2f}',
        'is_pending': is_pending,
    }
    return render(request, 'affiliate_ui/dashboard.html', context)


def _eligible_offers(request):
    """Active offers the affiliate may browse: scoped to their brand.

    Unbranded (legacy / network-wide) offers stay visible to everyone; another
    brand's offers are never shown — preserving brand isolation.

    Offers owned by an advertiser are only shown once that advertiser is
    APPROVED **and** email-verified: a pending advertiser's offers (and a
    suspended/rejected advertiser's offers) are hidden from affiliates. Offers
    with no advertiser link (legacy / network-wide) stay visible.
    """
    brand = getattr(request, 'brand', None)
    approved = Advertiser.AdvertiserStatus.APPROVED
    return (
        Offer.objects
        .filter(status=ACTIVE_STATUS)
        .filter(Q(brand=brand) | Q(brand__isnull=True))
        .filter(
            Q(advertiser__isnull=True)
            | Q(advertiser__advertiser_status=approved, advertiser__email_verified=True)
        )
    )


def _parse_decimal(raw):
    try:
        return Decimal(raw)
    except (InvalidOperation, TypeError, ValueError):
        return None


@require_approved_affiliate
def offer_list(request):
    search_query = (request.GET.get('search') or '').strip()
    category_id = request.GET.get('category') or None
    country = (request.GET.get('country') or '').strip().upper()
    revenue_model = request.GET.get('revenue_model') or ''
    traffic_source_id = request.GET.get('traffic_source') or None
    payout_min = _parse_decimal(request.GET.get('payout_min'))
    payout_max = _parse_decimal(request.GET.get('payout_max'))

    offers = _eligible_offers(request).prefetch_related(
        Prefetch('payouts', queryset=Payout.objects.order_by('-payout')),
        'categories',
    )

    if search_query:
        offers = offers.filter(title__icontains=search_query)
    if category_id:
        offers = offers.filter(categories__id=category_id)
    if revenue_model in dict(revenue_models):
        offers = offers.filter(revenue_model=revenue_model)
    if traffic_source_id:
        offers = offers.filter(
            offertrafficsource__traffic_source_id=traffic_source_id,
            offertrafficsource__allowed=True,
        )
    if payout_min is not None:
        offers = offers.filter(payouts__payout__gte=payout_min)
    if payout_max is not None:
        offers = offers.filter(payouts__payout__lte=payout_max)

    offers = offers.distinct()

    # Country filter applies the offer's include/exclude targeting logic. Done in
    # Python so ALLOW_ALL / ALLOW_LIST / BLOCK_LIST semantics stay in one place
    # (Offer.accepts_country).
    offer_rows = list(offers)
    if country:
        offer_rows = [o for o in offer_rows if o.accepts_country(country)]

    context = {
        'offers': offer_rows,
        'categories': Category.objects.all(),
        'traffic_sources': TrafficSource.objects.order_by('name'),
        'revenue_model_choices': revenue_models,
        'country_choices': country_choices(),
        'search_query': search_query,
        'selected_category': int(category_id) if category_id else None,
        'selected_country': country,
        'selected_revenue_model': revenue_model,
        'selected_traffic_source': int(traffic_source_id) if traffic_source_id else None,
        'payout_min': request.GET.get('payout_min', ''),
        'payout_max': request.GET.get('payout_max', ''),
    }
    return render(request, 'affiliate_ui/offers.html', context)


def generate_tracking_link(offer_id: int, pid: int) -> str:
    base_url = settings.TRACKER_URL
    url = f"{base_url}/click?offer_id={offer_id}&pid={pid}"
    return url


@require_POST
@login_required
def affiliate_logout(request):
    auth_logout(request)
    return redirect('/')


@require_approved_affiliate
def offer_detail(request, offer_id):
    offer = get_object_or_404(_eligible_offers(request), pk=offer_id)
    tracking_link = generate_tracking_link(offer_id, request.user.id)
    context = {
        'offer': offer,
        'tracking_link': tracking_link,
    }
    return render(request, 'affiliate_ui/offer_details.html', context)


class AffiliateLoginView(LoginView):
    template_name = 'affiliate_ui/login.html'
    redirect_authenticated_user = True
