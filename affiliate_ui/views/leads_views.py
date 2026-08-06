"""Affiliate-facing 'My Leads' page at /partner/leads/ — an affiliate can see
every lead they've submitted (either channel) and manually inject any of
their own leads to a configured buyer.

Ownership is enforced server-side (Lead.objects.filter(..., affiliate=
request.user)) on the inject endpoint, not just hidden in the UI — a direct
POST with someone else's lead id must not be able to inject it."""
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST

from affiliate_ui.gates import require_approved_affiliate
from impersonation.decorators import block_when_impersonating
from leadgen import canonical_status
from leadgen.models import Lead, LeadBuyer, LeadInjection
from leadgen.services import attach_latest_injections, inject_leads_to_buyer, summarize_injection_results
from leadgen.status_sync import attach_affiliate_phase


def _available_buyers(request):
    """Buyers this affiliate's leads may be injected to — strictly their own
    brand's.

    Paul ruled on outbound scoping (2026-08-05): a LeadBuyer belongs to
    exactly one Brand, which routes only to its own buyers and owns the payout
    relationship. The null-brand fallback this used to carry — "a
    platform-level destination any brand may route to" — is now incorrect, not
    merely undecided, so it is gone.

    Scoped to the affiliate's OWN brand rather than the request host, for the
    same reason offers are (see affiliate_ui.views.general_views.
    offers_for_affiliate): BrandMiddleware derives request.brand from the Host
    header and falls back to the default brand, and affiliate login is not
    brand-gated. Host-scoping here would offer an affiliate buyers that
    leadgen.services.start_injection then refuses at the wire, because the
    lead's brand and the buyer's would not match — a picker full of choices
    that cannot work.
    """
    brand = getattr(getattr(request.user, 'profile', None), 'brand', None)
    if brand is None:
        return LeadBuyer.objects.none()
    return LeadBuyer.objects.filter(is_active=True, brand=brand).order_by('name')


PAGE_SIZE = 50

# Filters this page understands. Deliberately the SAME vocabulary as the pull
# API's doc_filters (leadgen.api_views.LeadListView) wherever they overlap —
# `status` means canonical_status in both, `source_id` is an exact match in
# both — so an affiliate reading the API doc and an affiliate using the page
# are not learning two different systems. `q` and the date bounds are
# UI-only: the API's equivalents are `ids` and `updated_since`, which are
# reconcile tools rather than things a human types into a box.
def _filter_leads(qs, params):
    """Apply the request's filters to an ALREADY ownership-scoped queryset.

    Takes the scoped queryset rather than building its own, so this function
    cannot widen ownership however it is called — the affiliate= filter is
    applied by the caller before this is ever reached, and nothing here
    removes it. Returns (queryset, active_filters_dict).

    Unrecognised or unparseable values are IGNORED rather than erroring,
    matching the pull API's own posture: a bad `updated_since` there is
    dropped, not 400'd. A filter box is not a validation surface.
    """
    active = {}

    status = (params.get('status') or '').strip()
    if status in canonical_status.VALUES:
        qs = qs.filter(canonical_status=status)
        active['status'] = status

    delivery = (params.get('delivery') or '').strip()
    if delivery in {value for value, _label in Lead.STATUS_CHOICES}:
        qs = qs.filter(status=delivery)
        active['delivery'] = delivery

    source_id = (params.get('source_id') or '').strip()
    if source_id:
        qs = qs.filter(source_id=source_id)
        active['source_id'] = source_id

    q = (params.get('q') or '').strip()
    if q:
        # Free-text over the three things an affiliate actually has to hand
        # when chasing one lead: the consumer's email or phone, or their own
        # tracking id. Deliberately NOT name — names are not unique enough to
        # be a lookup key, and icontains over them invites full scans.
        qs = qs.filter(
            Q(email__icontains=q) | Q(phone__icontains=q) | Q(source_id__icontains=q))
        active['q'] = q

    date_from = parse_date((params.get('date_from') or '').strip())
    if date_from:
        qs = qs.filter(created_at__date__gte=date_from)
        active['date_from'] = params.get('date_from', '').strip()

    date_to = parse_date((params.get('date_to') or '').strip())
    if date_to:
        qs = qs.filter(created_at__date__lte=date_to)
        active['date_to'] = params.get('date_to', '').strip()

    return qs, active


@require_approved_affiliate
def my_leads(request):
    """The affiliate's own leads, filtered and paginated.

    Previously a hard `[:200]` slice with no filters: an affiliate with more
    than 200 leads simply could not reach the rest, and had no way to find one
    lead by email or tracking id. The pull API has had this filtering since
    it shipped; this brings the page to parity so the two surfaces agree.

    Ownership is scoped FIRST and separately from filtering — see
    _filter_leads — so no combination of query parameters can widen what an
    affiliate sees beyond their own leads.
    """
    qs = Lead.objects.filter(affiliate=request.user).order_by('-created_at')
    total_unfiltered = qs.count()
    qs, active_filters = _filter_leads(qs, request.GET)

    paginator = Paginator(qs, PAGE_SIZE)
    # get_page (not page()) clamps: a junk or out-of-range ?page= lands on a
    # real page instead of raising. Same "ignore, don't error" posture as the
    # filters themselves.
    page = paginator.get_page(request.GET.get('page'))

    leads = list(page.object_list)
    attach_latest_injections(leads)
    attach_affiliate_phase(leads)

    # Query string minus `page`, so the pager can preserve active filters
    # without accumulating page= values.
    querystring = request.GET.copy()
    querystring.pop('page', None)

    return render(request, 'affiliate_ui/leads.html', {
        'leads': leads,
        'page_obj': page,
        'paginator': paginator,
        'buyers': _available_buyers(request),
        'active_filters': active_filters,
        'filter_querystring': querystring.urlencode(),
        'total_unfiltered': total_unfiltered,
        'canonical_status_choices': canonical_status.CHOICES,
        'delivery_status_choices': Lead.STATUS_CHOICES,
    })


def _back_to_my_leads(request):
    """Redirect to My Leads, PRESERVING the filters the affiliate was viewing.

    Injecting from a filtered page used to bounce back to the unfiltered
    first page, so an affiliate working through "everything still unrouted"
    lost their place on every action and had to re-apply the filter to find
    the next batch. The filter state travels in a hidden field on the inject
    form (see leads.html)."""
    base = reverse('affiliate_ui:my_leads')
    qs = (request.POST.get('filter_querystring') or '').lstrip('?')
    return redirect(f'{base}?{qs}' if qs else base)


@block_when_impersonating
@require_approved_affiliate
@require_POST
def inject_my_leads(request):
    # Validate the shape before querying: get_object_or_404(pk='') raises
    # ValueError from the field's get_prep_value, which is a 500, not a 404 —
    # so a malformed or absent buyer_id (an empty select, a hand-rolled POST)
    # crashed rather than being refused. Only the pk lookup needs this; the
    # queryset itself is already brand- and active-scoped.
    buyer_id = (request.POST.get('buyer_id') or '').strip()
    if not buyer_id.isdigit():
        messages.error(request, 'Select a buyer to inject to.')
        return _back_to_my_leads(request)

    buyer = get_object_or_404(_available_buyers(request), pk=buyer_id)
    lead_ids = request.POST.getlist('lead_ids')

    # Ownership scoping: only leads this affiliate actually submitted, even
    # if a lead_id for someone else's lead is included in the POST body.
    leads = list(Lead.objects.filter(pk__in=lead_ids, affiliate=request.user))
    if not leads:
        messages.error(request, 'Select at least one of your own leads.')
        return _back_to_my_leads(request)

    results = inject_leads_to_buyer(leads, buyer)
    delivered, duplicate, failed = summarize_injection_results(results)
    for lead, injection in results:
        if injection.status not in (LeadInjection.STATUS_DELIVERED, LeadInjection.STATUS_DUPLICATE):
            messages.warning(
                request, f'{lead.full_name or lead.email}: {injection.failure_reason or injection.status}')

    level = messages.SUCCESS if not failed else messages.WARNING
    messages.add_message(
        request, level,
        f'Injected to {buyer.name}: {delivered} delivered, {duplicate} duplicate, {failed} failed.')
    return _back_to_my_leads(request)
