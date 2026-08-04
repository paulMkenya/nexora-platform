"""Brand-admin offer management in the operator console (/admin/offers/).

This is the operator-console counterpart to the advertiser self-service offer
flow (``advertiser_ui``). The two share the exact same form field set (see
``offer.offer_form``); the difference is scope and stamping:

  * ADVERTISER  — manages only their OWN offers (``advertiser_ui``).
  * BRAND ADMIN — manages EVERY offer in their OWN brand, and creates offers on
    behalf of any advertiser in that brand (must pick the advertiser).
  * PLATFORM OWNER (superuser) — every offer across every brand; may pick any
    brand's advertisers.
  * AFFILIATE MANAGER — no offer management at all (blocked by the gate).

Scoping is enforced at the OBJECT level: every edit/status lookup goes through
``_scoped_offers`` so a brand admin reaching another brand's offer by direct ID
gets a 404, not just an empty list. The chosen advertiser on create is likewise
re-validated against ``_scoped_advertisers`` server-side — the dropdown is a
hint, never the authority.
"""
from django.contrib import messages
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from brands.permissions import brand_admin_required
from brands.scoping import scope_brand, sees_all_brands
from offer.models import (
    ACTIVE_STATUS, Advertiser, Category, Offer, PAUSED_STATUS, offer_statuses,
)
from offer.offer_form import (
    create_offer_from_post,
    offer_form_ctx,
    update_offer_from_post,
    validate_offer_post,
)


# ── scoping helpers ──────────────────────────────────────────────────────────

def _scoped_offers(request):
    """Offer queryset visible to the current operator.

    Superuser (platform owner) sees every brand's offers; a brand admin is
    confined to their assigned brand. This queryset is what makes "another
    brand's offer is a 404 even by direct ID" true — object lookups go through
    it.
    """
    qs = Offer.objects.select_related('advertiser', 'brand').prefetch_related(
        'categories', 'countries')
    if sees_all_brands(request.user):
        return qs
    return qs.filter(brand=scope_brand(request))


def _scoped_advertisers(request):
    """Advertisers the operator may create/assign offers for.

    Brand admin → advertisers in their own brand only. Superuser → all.
    """
    qs = Advertiser.objects.select_related('brand').order_by('company')
    if sees_all_brands(request.user):
        return qs
    return qs.filter(brand=scope_brand(request))


def _get_offer_or_404(request, offer_id):
    """Fetch an offer, 404 if outside the operator's brand scope."""
    return get_object_or_404(_scoped_offers(request), pk=offer_id)


# ── list ─────────────────────────────────────────────────────────────────────

@brand_admin_required
def offer_list(request):
    qs = _scoped_offers(request)

    status_filter = request.GET.get('status', '').strip()
    advertiser_filter = request.GET.get('advertiser', '').strip()
    category_filter = request.GET.get('category', '').strip()

    if status_filter:
        qs = qs.filter(status=status_filter)
    if advertiser_filter.isdigit():
        qs = qs.filter(advertiser_id=int(advertiser_filter))
    if category_filter.isdigit():
        qs = qs.filter(categories__id=int(category_filter))

    qs = qs.order_by('-id').distinct()

    status_counts = dict(
        _scoped_offers(request).values_list('status').annotate(n=Count('id', distinct=True))
    )

    return render(request, 'admin_shared/offers.html', {
        'active': 'offers',
        'shell_role': 'admin',
        'page_title': 'Offers',
        'offers': qs,
        'status_filter': status_filter,
        'advertiser_filter': advertiser_filter,
        'category_filter': category_filter,
        'status_choices': offer_statuses,
        'advertisers': _scoped_advertisers(request),
        'categories': Category.objects.all(),
        'status_counts': status_counts,
        'total_count': sum(status_counts.values()),
        'sees_all_brands': sees_all_brands(request.user),
        'ACTIVE_STATUS': ACTIVE_STATUS,
        'PAUSED_STATUS': PAUSED_STATUS,
    })


# ── create / edit ────────────────────────────────────────────────────────────

def _form_ctx(request, offer=None):
    """offer_form_ctx + the brand-admin-only advertiser picker."""
    ctx = offer_form_ctx(request, offer)
    if request.method == 'POST':
        selected_advertiser = request.POST.get('advertiser', '')
    elif offer is not None:
        selected_advertiser = str(offer.advertiser_id or '')
    else:
        selected_advertiser = ''
    ctx.update({
        'active': 'offers',
        'advertisers': _scoped_advertisers(request),
        'selected_advertiser': selected_advertiser,
        'shell_role': 'admin',
        'page_title': 'Edit Offer' if offer is not None else 'New Offer',
    })
    return ctx


def _resolve_advertiser(request):
    """The chosen advertiser, re-validated against the operator's scope.

    Returns the Advertiser or ``None`` if missing/out-of-scope (the caller turns
    that into a form error — never a silent cross-brand write).
    """
    adv_id = (request.POST.get('advertiser') or '').strip()
    if not adv_id.isdigit():
        return None
    return _scoped_advertisers(request).filter(pk=int(adv_id)).first()


@brand_admin_required
def offer_create(request):
    if request.method == 'POST':
        _, _, _, errors = validate_offer_post(request)
        advertiser = _resolve_advertiser(request)
        if advertiser is None:
            errors = errors + ['Select an advertiser in your brand.']
        if errors:
            for err in errors:
                messages.error(request, err)
            return render(request, 'admin_shared/offer_form.html', _form_ctx(request))

        # Stamp the offer with the chosen advertiser AND that advertiser's brand
        # (== the operator's brand for a brand admin; any brand for the owner).
        offer = create_offer_from_post(
            request, advertiser=advertiser, brand=advertiser.brand)
        messages.success(request, f'Offer "{offer.title}" created.')
        return redirect('offers_admin:list')

    return render(request, 'admin_shared/offer_form.html', _form_ctx(request))


@brand_admin_required
def offer_edit(request, offer_id):
    offer = _get_offer_or_404(request, offer_id)

    if request.method == 'POST':
        _, _, _, errors = validate_offer_post(request)
        advertiser = _resolve_advertiser(request)
        if advertiser is None:
            errors = errors + ['Select an advertiser in your brand.']
        if errors:
            for err in errors:
                messages.error(request, err)
            return render(request, 'admin_shared/offer_form.html', _form_ctx(request, offer))

        # Re-assignment stays within scope: the new advertiser (and its brand)
        # are validated through _scoped_advertisers above. Set them before the
        # shared updater's full save() persists the row.
        offer.advertiser = advertiser
        offer.brand = advertiser.brand
        update_offer_from_post(request, offer)
        messages.success(request, f'Offer "{offer.title}" updated.')
        return redirect('offers_admin:list')

    return render(request, 'admin_shared/offer_form.html', _form_ctx(request, offer))


@require_POST
@brand_admin_required
def offer_set_status(request, offer_id):
    """Pause/activate (or set any valid status) for an in-scope offer."""
    offer = _get_offer_or_404(request, offer_id)

    target = request.POST.get('status', '')
    if target not in dict(offer_statuses):
        target = PAUSED_STATUS if offer.status == ACTIVE_STATUS else ACTIVE_STATUS

    offer.status = target
    offer.save(update_fields=['status'])
    messages.success(request, f'Offer "{offer.title}" set to {target}.')
    return redirect('offers_admin:list')
