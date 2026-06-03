import csv

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout
from django.core.exceptions import ObjectDoesNotExist
from django.db.models import Count
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from offer.models import (
    ACTIVE_STATUS, ALLOW_ALL, CPA, Category, Offer, PAUSED_STATUS,
    TrafficSource, country_modes, offer_statuses, revenue_models,
)

from advertiser.decorators import advertiser_required
from advertiser_ui.services import (
    CONVERSION_STATUSES,
    bulk_update_conversions,
    get_conversions_for_export,
    get_conversions_page,
    get_dashboard_data,
    get_inbound_postback_log,
    get_offers_list,
    get_or_create_postback_key,
    parse_conversion_filters,
    regenerate_postback_key,
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


# ── postbacks ──────────────────────────────────────────────────────────────

@advertiser_required
def postbacks(request):
    advertiser = _get_advertiser(request)
    if not advertiser:
        return render(request, 'advertiser_ui/postbacks.html', {'no_account': True})

    key, _ = get_or_create_postback_key(advertiser)
    log    = get_inbound_postback_log(advertiser)

    canonical_url = (
        f"{settings.TRACKER_URL}/postback"
        f"?click_id={{click_id}}&status={{status}}&sum={{sum}}"
    )
    signed_url = canonical_url + '&sig={sig}'

    return render(request, 'advertiser_ui/postbacks.html', {
        'key':          key,
        'log':          log,
        'canonical_url': canonical_url,
        'signed_url':   signed_url,
        'enforce':      settings.ENFORCE_POSTBACK_HMAC,
    })


@require_POST
@advertiser_required
def regenerate_secret(request):
    advertiser = _get_advertiser(request)
    if not advertiser:
        return HttpResponseForbidden()
    regenerate_postback_key(advertiser)
    messages.success(request, 'HMAC secret regenerated. Update your integration.')
    return redirect('advertiser_ui:postbacks')


@advertiser_required
def mmp_callbacks(request):
    advertiser = _get_advertiser(request)
    if not advertiser:
        return render(request, 'advertiser_ui/mmp_callbacks.html', {'no_account': True})

    from datetime import timedelta
    from mmp.models import MMPCallback

    since = timezone.now() - timedelta(hours=24)
    offer_ids = list(Offer.objects.filter(advertiser=advertiser).values_list('id', flat=True))

    callbacks_qs = (
        MMPCallback.objects
        .filter(offer_id__in=offer_ids, created_at__gte=since)
        .select_related('offer')
        .order_by('-created_at')[:100]
    )

    total_24h = MMPCallback.objects.filter(offer_id__in=offer_ids, created_at__gte=since).count()
    processed_24h = MMPCallback.objects.filter(
        offer_id__in=offer_ids, created_at__gte=since, processed=True).count()

    mmp_offers_qs = (
        Offer.objects
        .filter(advertiser=advertiser, mmp__isnull=False)
        .select_related('mmp')
    )
    mmp_offers = []
    for o in mmp_offers_qs:
        mmp_offers.append({
            'id': o.id,
            'title': o.title,
            'mmp_name': o.mmp.name,
            'mmp_app_id': o.mmp_app_id,
            'callbacks_24h': MMPCallback.objects.filter(
                offer=o, created_at__gte=since).count(),
        })

    return render(request, 'advertiser_ui/mmp_callbacks.html', {
        'callbacks': callbacks_qs,
        'total_24h': total_24h,
        'processed_24h': processed_24h,
        'unprocessed_24h': total_24h - processed_24h,
        'mmp_offers': mmp_offers,
        'mmp_offers_count': len(mmp_offers),
    })


@advertiser_required
def wallet(request):
    advertiser = _get_advertiser(request)
    if not advertiser:
        return render(request, 'advertiser_ui/wallet.html', {'no_account': True})

    try:
        from billing.models import AdvertiserWallet
        w = AdvertiserWallet.objects.get(advertiser=advertiser)
    except Exception:
        w = None

    transactions = []
    topups = []
    invoices = []
    if w:
        transactions = w.transactions.order_by('-created_at')[:30]
        topups = w.topups.order_by('-created_at')[:10]
        invoices = w.invoices.order_by('-period_start')[:12]

    return render(request, 'advertiser_ui/wallet.html', {
        'wallet': w,
        'transactions': transactions,
        'topups': topups,
        'invoices': invoices,
    })


@advertiser_required
def settings_view(request):
    from user_profile.geo import country_choices, country_display

    advertiser = _get_advertiser(request)

    if request.method == 'POST' and advertiser is not None:
        country = (request.POST.get('country') or '').upper()
        valid = {code for code, _ in country_choices(include_blank=False)}
        if country and country not in valid:
            messages.error(request, 'Please select a valid country.')
        else:
            advertiser.country = country
            advertiser.save(update_fields=['country'])
            messages.success(request, 'Settings updated.')
        return redirect('advertiser_ui:settings')

    return render(request, 'advertiser_ui/settings.html', {
        'advertiser': advertiser,
        'country_choices': country_choices(),
        'country_display': country_display(advertiser.country) if advertiser else '',
    })


def advertiser_logout(request):
    logout(request)
    return redirect('affiliate_ui:login')


# ── offer create / edit / status ────────────────────────────────────────────

def _offer_form_ctx(request, offer=None):
    """Build the context for offer_form.html (create or edit).

    On a POST re-render the submitted values win (so validation errors don't
    wipe the form); otherwise we seed from the edited offer, or empty defaults
    for a fresh create.
    """
    from offer.currencies import currency_choices
    from user_profile.geo import country_choices

    if request.method == 'POST':
        data = {
            'title': request.POST.get('title', ''),
            'description': request.POST.get('description', ''),
            'tracking_link': request.POST.get('tracking_link', ''),
            'preview_link': request.POST.get('preview_link', ''),
            'icon': request.POST.get('icon', ''),
            'status': request.POST.get('status', ACTIVE_STATUS),
            'revenue_model': request.POST.get('revenue_model', CPA),
            'country_mode': request.POST.get('country_mode', ALLOW_ALL),
        }
        selected_countries = set(request.POST.getlist('countries'))
        selected_categories = set(request.POST.getlist('categories'))
        selected_traffic = set(request.POST.getlist('traffic_sources'))
    elif offer is not None:
        data = {
            'title': offer.title,
            'description': offer.description,
            'tracking_link': offer.tracking_link,
            'preview_link': offer.preview_link,
            'icon': offer.icon or '',
            'status': offer.status,
            'revenue_model': offer.revenue_model,
            'country_mode': offer.country_mode,
        }
        selected_countries = set(offer.countries.values_list('iso', flat=True))
        selected_categories = {str(cid) for cid in offer.categories.values_list('id', flat=True)}
        selected_traffic = {
            str(tid) for tid in offer.offertrafficsource_set
            .filter(allowed=True).values_list('traffic_source_id', flat=True)
        }
    else:
        data = {'status': ACTIVE_STATUS, 'revenue_model': CPA, 'country_mode': ALLOW_ALL}
        selected_countries = set()
        selected_categories = set()
        selected_traffic = set()

    return {
        'offer': offer,
        'is_edit': offer is not None,
        'data': data,
        'status_choices': offer_statuses,
        'revenue_model_choices': revenue_models,
        'country_mode_choices': country_modes,
        'country_choices': country_choices(include_blank=False),
        'selected_countries': selected_countries,
        'categories': Category.objects.all(),
        'selected_categories': selected_categories,
        'traffic_sources': TrafficSource.objects.order_by('name'),
        'selected_traffic': selected_traffic,
        'currency_choices': currency_choices(),
    }


def _apply_offer_targeting(offer, request):
    """Set the offer's countries, categories and accepted traffic sources from POST.

    Country *mode* and the country list together drive ``offer.accepts_country``;
    traffic sources are stored through ``OfferTrafficSource`` (allowed=True).
    """
    from countries_plus.models import Country
    from offer.models import OfferTrafficSource

    iso_codes = [c.strip().upper() for c in request.POST.getlist('countries') if c.strip()]
    offer.countries.set(Country.objects.filter(iso__in=iso_codes))
    cat_ids = [c for c in request.POST.getlist('categories') if c.isdigit()]
    offer.categories.set(Category.objects.filter(id__in=cat_ids))

    ts_ids = [t for t in request.POST.getlist('traffic_sources') if t.isdigit()]
    valid_ids = set(
        TrafficSource.objects.filter(id__in=ts_ids).values_list('id', flat=True))
    offer.offertrafficsource_set.exclude(traffic_source_id__in=valid_ids).delete()
    existing = set(
        offer.offertrafficsource_set.values_list('traffic_source_id', flat=True))
    for tid in valid_ids - existing:
        OfferTrafficSource.objects.create(
            offer=offer, traffic_source_id=tid, allowed=True)


def _maybe_create_initial_payout(offer, request):
    """Optionally create one Payout row from the create form's payout fields."""
    from decimal import Decimal, InvalidOperation
    from offer.models import Currency, FIXED_PAYOUT, Payout

    raw_payout = (request.POST.get('payout_amount') or '').strip()
    if not raw_payout:
        return
    try:
        payout_val = Decimal(raw_payout)
        revenue_val = Decimal((request.POST.get('revenue') or '').strip() or raw_payout)
    except (InvalidOperation, ValueError):
        messages.warning(request, 'Payout amount ignored (not a valid number).')
        return
    currency = Currency.objects.filter(code=(request.POST.get('currency') or '').strip()).first()
    if currency is None:
        messages.warning(request, 'Payout ignored (select a currency).')
        return
    Payout.objects.create(
        offer=offer, revenue=revenue_val, payout=payout_val,
        currency=currency, goal_value='1', type=FIXED_PAYOUT,
    )


def _validate_offer_post(request):
    """Return (title, tracking_link, status, errors) parsed from the request."""
    title = (request.POST.get('title') or '').strip()
    tracking_link = (request.POST.get('tracking_link') or '').strip()
    status = request.POST.get('status', ACTIVE_STATUS)
    if status not in dict(offer_statuses):
        status = ACTIVE_STATUS
    errors = []
    if not title:
        errors.append('Title is required.')
    if not tracking_link:
        errors.append('Tracking link is required.')
    return title, tracking_link, status, errors


def _parse_choice(request, field, choices, default):
    """Return a POSTed value if it is a valid choice, else the default."""
    value = request.POST.get(field, default)
    return value if value in dict(choices) else default


@advertiser_required
def offer_create(request):
    advertiser = _get_advertiser(request)
    if not advertiser:
        return render(request, 'advertiser_ui/offer_form.html', {'no_account': True})

    if request.method == 'POST':
        title, tracking_link, status, errors = _validate_offer_post(request)
        if errors:
            for err in errors:
                messages.error(request, err)
            return render(request, 'advertiser_ui/offer_form.html', _offer_form_ctx(request))

        offer = Offer.objects.create(
            title=title,
            description=(request.POST.get('description') or '').strip(),
            tracking_link=tracking_link,
            preview_link=(request.POST.get('preview_link') or '').strip(),
            icon=(request.POST.get('icon') or '').strip(),
            status=status,
            revenue_model=_parse_choice(request, 'revenue_model', revenue_models, CPA),
            country_mode=_parse_choice(request, 'country_mode', country_modes, ALLOW_ALL),
            advertiser=advertiser,
            brand=getattr(request, 'brand', None),
        )
        _apply_offer_targeting(offer, request)
        _maybe_create_initial_payout(offer, request)
        messages.success(request, f'Offer "{offer.title}" created.')
        return redirect('advertiser_ui:offers')

    return render(request, 'advertiser_ui/offer_form.html', _offer_form_ctx(request))


def _get_own_offer(request, advertiser, offer_id):
    """Fetch an offer strictly scoped to this advertiser AND request.brand."""
    return get_object_or_404(
        Offer, pk=offer_id, advertiser=advertiser, brand=getattr(request, 'brand', None),
    )


@advertiser_required
def offer_edit(request, offer_id):
    advertiser = _get_advertiser(request)
    if not advertiser:
        return HttpResponseForbidden()
    offer = _get_own_offer(request, advertiser, offer_id)

    if request.method == 'POST':
        title, tracking_link, status, errors = _validate_offer_post(request)
        if not request.POST.get('status'):
            status = offer.status
        if errors:
            for err in errors:
                messages.error(request, err)
            return render(request, 'advertiser_ui/offer_form.html', _offer_form_ctx(request, offer))

        offer.title = title
        offer.description = (request.POST.get('description') or '').strip()
        offer.tracking_link = tracking_link
        offer.preview_link = (request.POST.get('preview_link') or '').strip()
        offer.icon = (request.POST.get('icon') or '').strip()
        offer.status = status
        offer.revenue_model = _parse_choice(request, 'revenue_model', revenue_models, offer.revenue_model)
        offer.country_mode = _parse_choice(request, 'country_mode', country_modes, offer.country_mode)
        offer.save()
        _apply_offer_targeting(offer, request)
        messages.success(request, f'Offer "{offer.title}" updated.')
        return redirect('advertiser_ui:offers')

    return render(request, 'advertiser_ui/offer_form.html', _offer_form_ctx(request, offer))


@require_POST
@advertiser_required
def offer_set_status(request, offer_id):
    """Pause/activate (or set any valid status) for one of the advertiser's offers."""
    advertiser = _get_advertiser(request)
    if not advertiser:
        return HttpResponseForbidden()
    offer = _get_own_offer(request, advertiser, offer_id)

    target = request.POST.get('status', '')
    if target not in dict(offer_statuses):
        # No explicit target → toggle between Active and Paused.
        target = PAUSED_STATUS if offer.status == ACTIVE_STATUS else ACTIVE_STATUS

    offer.status = target
    offer.save(update_fields=['status'])
    messages.success(request, f'Offer "{offer.title}" set to {target}.')
    return redirect('advertiser_ui:offers')
