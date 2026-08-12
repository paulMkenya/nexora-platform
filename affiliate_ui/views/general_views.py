from decimal import Decimal, InvalidOperation

from django.contrib.auth import logout as auth_logout
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q, Sum, Prefetch
from django.shortcuts import redirect, render, get_object_or_404
from django.contrib.auth.views import LoginView
from django.views.decorators.http import require_POST

from affiliate_ui.gates import require_approved_affiliate
from brands.links import affiliate_click_link
from nexora import charts
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
        'offer_rows': _offer_leaderboard(request.user),
        'payout_timeline': _payout_timeline(
            request.user,
            clicks_count=clicks_count,
            conversions=conversions,
            total_earnings=total_earnings,
        ),
    }
    return render(request, 'affiliate_ui/dashboard.html', context)


def _offer_leaderboard(affiliate, *, limit=5):
    """Top offers for this affiliate by clicks, with conversions and EPC.

    Scoped through ``offers_for_affiliate`` rather than "every offer I have a
    click on", so a click recorded before a brand reassignment can't surface an
    offer the affiliate is no longer entitled to see (see that function's
    docstring for why host-independent brand scoping is the rule here).

    Two grouped queries and a dict merge — not one query per offer.
    """
    offers = list(offers_for_affiliate(affiliate))
    if not offers:
        return []

    clicks_by_offer = {
        row['offer']: row['n']
        for row in Click.objects.filter(affiliate=affiliate, offer__in=offers)
        .values('offer').annotate(n=Count('id'))
    }
    conv_by_offer = {
        row['offer']: row
        for row in Conversion.objects.filter(affiliate=affiliate, offer__in=offers)
        .values('offer').annotate(
            n=Count('id'),
            approved=Count('id', filter=Q(status=APPROVED_STATUS)),
            earned=Sum('payout', filter=Q(status=APPROVED_STATUS)),
        )
    }

    rows = []
    for offer in offers:
        clicks = clicks_by_offer.get(offer.pk, 0)
        conv = conv_by_offer.get(offer.pk) or {}
        approved = conv.get('approved') or 0
        earned = conv.get('earned') or Decimal('0')

        # EPC is earnings per click — undefined with no clicks, and shown as
        # 0.00 rather than a divide-by-zero or a blank cell.
        epc = (Decimal(earned) / clicks) if clicks else Decimal('0')

        if clicks == 0:
            state, tone = 'Idle', 'muted'
        elif approved == 0:
            state, tone = 'Pending', 'warn'
        else:
            state, tone = 'Earning', 'pos'

        rows.append({
            'offer': offer,
            'clicks': clicks,
            'conversions': conv.get('n') or 0,
            'approved': approved,
            'earned': earned,
            'epc': epc,
            'state': state,
            'state_tone': tone,
        })

    rows.sort(key=lambda r: (r['clicks'], r['earned']), reverse=True)
    return rows[:limit]


def _payout_timeline(affiliate, *, clicks_count, conversions, total_earnings):
    """Progress toward this affiliate's next payout.

    Every number here is derived from data the affiliate can already see
    elsewhere (clicks, conversions, earnings, their own payout settings) — this
    panel reorganises it, it does not introduce a new source of truth.
    """
    from payouts.models import PayoutSettings

    settings_row = PayoutSettings.objects.filter(affiliate=affiliate).first()
    threshold = settings_row.min_threshold if settings_row else Decimal('50.00')
    net_terms = settings_row.net_terms if settings_row else 15

    # "Verified" = the click carried none of the automated fraud signals. This
    # mirrors what the fraud console counts as clean, so the two never disagree.
    verified_clicks = Click.objects.filter(
        affiliate=affiliate, is_bot=False, is_proxy=False, is_datacenter=False,
    ).count()

    conversions_total = conversions.count()
    conversions_approved = conversions.filter(status=APPROVED_STATUS).count()

    return {
        'clicks': charts.meter(verified_clicks, clicks_count, tone='blue'),
        'clicks_text': f'{verified_clicks} / {clicks_count}',
        'conversions': charts.meter(conversions_approved, conversions_total, tone='blue'),
        'conversions_text': f'{conversions_approved} / {conversions_total}',
        'threshold': charts.meter(total_earnings, threshold, tone='teal'),
        'threshold_text': f'${total_earnings:.2f} / ${threshold:.2f}',
        'net_terms': net_terms,
        'on_track': Decimal(total_earnings) >= threshold,
    }


def offers_for_affiliate(affiliate, *, historical=False):
    """THE single source of truth for which offers an affiliate may see or
    send to. Every affiliate-facing surface calls this — the offers page,
    offer detail, the generated API doc and its curl example, the reports
    filter, and the inbound API's offer_id validation — so none of them can
    drift from the others.

    Paul's ruling (2026-08-04): an affiliate belongs to exactly ONE brand and
    may see, browse, submit to, and be documented for ONLY that brand's
    offers.

    Two consequences worth stating, because both are deliberate:

    1. Scoping keys off ``affiliate.profile.brand`` — never the request host.
       BrandMiddleware resolves request.brand from the Host header and falls
       back to the default brand, and affiliate login is not brand-gated, so
       host-driven scoping let a brand-A affiliate reaching brand-B's domain
       see (and submit to) brand-B's offers. Host is now irrelevant here.

    2. An unbranded/shared offer is returned to NOBODY. There is no platform
       fallback: a null-brand offer is not "available to everyone", it is
       simply not an offer any affiliate may use. An affiliate with no brand
       therefore gets nothing at all, rather than matching the shared set.

    Advertiser gating is unchanged for everything an affiliate may act on: an
    advertiser's offers appear only once that advertiser is APPROVED and
    email-verified and not archived; offers with no advertiser link stay
    visible within the brand.

    ``historical=True`` keeps the brand rule and the null-brand exclusion but
    drops that availability gate, and exists for ONE caller: the reports offer
    filter. Reporting looks backwards. An affiliate who drove real traffic to
    an offer whose advertiser was later suspended, archived or un-verified
    still has those clicks and conversions, and their own earnings history
    must stay filterable — availability governs what you may newly send to,
    not what you already sent. Brand isolation still applies in full, so this
    can never surface another brand's offer; it only keeps your own history
    from silently disappearing.
    """
    brand = getattr(getattr(affiliate, 'profile', None), 'brand', None)
    if brand is None:
        return Offer.objects.none()

    qs = Offer.objects.filter(brand=brand)
    if historical:
        return qs

    approved = Advertiser.AdvertiserStatus.APPROVED
    return (
        qs
        .filter(status=ACTIVE_STATUS)
        .filter(
            Q(advertiser__isnull=True)
            | Q(
                advertiser__advertiser_status=approved,
                advertiser__email_verified=True,
                advertiser__is_archived=False,
            )
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

    offers = offers_for_affiliate(request.user).prefetch_related(
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


def generate_tracking_link(offer, pid: int, request=None) -> str:
    """Brand-aware click link for *offer* (built from the offer's brand domain)."""
    return affiliate_click_link(offer, pid, request=request)


@require_POST
@login_required
def affiliate_logout(request):
    auth_logout(request)
    return redirect('/')


@require_approved_affiliate
def offer_detail(request, offer_id):
    offer = get_object_or_404(offers_for_affiliate(request.user), pk=offer_id)
    tracking_link = generate_tracking_link(offer, request.user.id, request=request)
    context = {
        'offer': offer,
        'tracking_link': tracking_link,
    }
    return render(request, 'affiliate_ui/offer_details.html', context)


class AffiliateLoginView(LoginView):
    template_name = 'affiliate_ui/login.html'
    redirect_authenticated_user = True
