"""Shared building blocks for the offer create/edit form.

These helpers are the single source of truth for parsing and applying the offer
form fields (name, description, creative, revenue model, country targeting,
traffic sources, status, initial payout). They are deliberately framework-light
— each takes the ``request`` plus, where relevant, the ``Offer`` being edited —
so they can back BOTH surfaces that expose the same form:

  * the advertiser self-service portal (``advertiser_ui`` — an advertiser edits
    only their own offers), and
  * the brand-admin operator console (``brands.views.offer_views`` — a brand
    admin manages every offer in their brand and picks the advertiser).

The advertiser/brand stamping and object-level scoping are the caller's job;
everything here is about the shared field set.
"""
from django.contrib import messages

from offer.models import (
    ACTIVE_STATUS, ALLOW_ALL, CPA, Category, Offer, TrafficSource,
    country_modes, offer_statuses, revenue_models,
)


def offer_form_ctx(request, offer=None):
    """Build the context for the offer form (create or edit).

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


def apply_offer_targeting(offer, request):
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


def maybe_create_initial_payout(offer, request):
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


def validate_offer_post(request):
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


def parse_choice(request, field, choices, default):
    """Return a POSTed value if it is a valid choice, else the default."""
    value = request.POST.get(field, default)
    return value if value in dict(choices) else default


def create_offer_from_post(request, *, advertiser, brand):
    """Create and return an Offer from validated POST data + targeting + payout.

    Caller is responsible for having validated the post (``validate_offer_post``)
    and for choosing/authorising ``advertiser`` and ``brand``.
    """
    title, tracking_link, status, _ = validate_offer_post(request)
    offer = Offer.objects.create(
        title=title,
        description=(request.POST.get('description') or '').strip(),
        tracking_link=tracking_link,
        preview_link=(request.POST.get('preview_link') or '').strip(),
        icon=(request.POST.get('icon') or '').strip(),
        status=status,
        revenue_model=parse_choice(request, 'revenue_model', revenue_models, CPA),
        country_mode=parse_choice(request, 'country_mode', country_modes, ALLOW_ALL),
        advertiser=advertiser,
        brand=brand,
    )
    apply_offer_targeting(offer, request)
    maybe_create_initial_payout(offer, request)
    return offer


def update_offer_from_post(request, offer):
    """Apply validated POST data + targeting to an existing Offer and save it.

    Status is preserved when the form omits it (status-only changes go through
    the dedicated pause/activate action).
    """
    title, tracking_link, status, _ = validate_offer_post(request)
    if not request.POST.get('status'):
        status = offer.status

    offer.title = title
    offer.description = (request.POST.get('description') or '').strip()
    offer.tracking_link = tracking_link
    offer.preview_link = (request.POST.get('preview_link') or '').strip()
    offer.icon = (request.POST.get('icon') or '').strip()
    offer.status = status
    offer.revenue_model = parse_choice(request, 'revenue_model', revenue_models, offer.revenue_model)
    offer.country_mode = parse_choice(request, 'country_mode', country_modes, offer.country_mode)
    offer.save()
    apply_offer_targeting(offer, request)
    return offer
