"""The Distribution console (Phase 3 of the lead-distribution build) — a
purpose-built, shared-shell surface for the leads inbox, buyer roster, and
routing rules, replacing the raw table that used to sit bolted under the
operator dashboard. Django admin (leadgen/admin.py) stays available as the
power-user fallback and test surface — this console is the primary one.

Every view here is brand-scoped exactly like brands.views.admin_views.
dashboard: a superuser (platform owner) sees/acts across every brand, an
ordinary operator only ever sees/touches their own."""
import datetime
import json

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import get_user_model
from django.core.paginator import Paginator
from django.db.models import Avg, Count, DurationField, ExpressionWrapper, F, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from brands.scoping import scope_brand, sees_all_brands
from nexora import charts

from . import canonical_status
from .connectors import (
    ATTRIBUTION_SOURCE_PREFIX,
    MAPPABLE_LEAD_FIELDS,
    OPT_IN_LEAD_FIELDS,
    LeadBuyerError,
    get_connector,
)
from .serializers import ATTRIBUTION_FIELDS, SUB_FIELDS
from .forms import LeadBuyerForm, RoutingRuleForm
from .models import (
    AffiliateOfferLink, BoxType, Lead, LeadBuyer, LeadInjection, LeadStatusEvent, RoutingRule,
)
from .routing import attach_computed_chains, resolve_buyer_chain
from .services import attach_latest_injections
from .status_sync import StatusAuthorityError, apply_status_change, attach_affiliate_phase, go_live, revert_to_testing

PAGE_SIZE = 50


def _scoped_leads(request):
    show_all_brands = sees_all_brands(request.user)
    brand = scope_brand(request)
    qs = Lead.objects.select_related('offer', 'affiliate', 'brand').order_by('-created_at')
    if not show_all_brands:
        qs = qs.filter(brand=brand)
    return qs, brand, show_all_brands


def _scoped_buyers(request, *, active_only=False):
    show_all_brands = sees_all_brands(request.user)
    brand = scope_brand(request)
    qs = LeadBuyer.objects.all()
    if active_only:
        qs = qs.filter(is_active=True)
    if not show_all_brands:
        # Strictly the operator's own brand: buyers are brand-owned, and there
        # is no platform-wide buyer to fall back to any more.
        qs = qs.filter(brand=brand)
    return qs.order_by('name'), brand, show_all_brands


@staff_member_required
def leads_console(request):
    """The primary leads surface (build guide Phase 3.2): source channel,
    matched offer, geo, affiliate, current status (a clear pill, incl.
    unrouted), and the computed buyer chain — what routing WOULD do, not
    what it has done — alongside per-lead/bulk "Route now". Nothing here
    triggers automatically; "Route now" is the deliberate manual trigger
    for leadgen.failover.advance_chain, same posture as every other
    kill-switched action in this app."""
    leads_qs, brand, show_all_brands = _scoped_leads(request)

    lead_affiliates = get_user_model().objects.filter(
        pk__in=leads_qs.exclude(affiliate__isnull=True).values_list('affiliate_id', flat=True).distinct()
    ).order_by('username')

    selected_affiliate_id = request.GET.get('affiliate_id') or ''
    if selected_affiliate_id.isdigit():
        leads_qs = leads_qs.filter(affiliate_id=selected_affiliate_id)
    else:
        selected_affiliate_id = ''

    selected_status = request.GET.get('status') or ''
    if selected_status in dict(Lead.STATUS_CHOICES):
        leads_qs = leads_qs.filter(status=selected_status)

    paginator = Paginator(leads_qs, PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get('page'))
    leads = list(page_obj.object_list)

    attach_latest_injections(leads)
    attach_computed_chains(leads)
    attach_affiliate_phase(leads)

    buyers, _, _ = _scoped_buyers(request, active_only=True)

    return render(request, 'leadgen/console/leads.html', {
        'shell_role': 'admin',
        'page_title': 'Leads',
        'leads': leads,
        'page_obj': page_obj,
        'buyers': buyers,
        'lead_affiliates': lead_affiliates,
        'selected_affiliate_id': selected_affiliate_id,
        'selected_status': selected_status,
        'status_choices': Lead.STATUS_CHOICES,
        'canonical_status_choices': canonical_status.CHOICES,
        'show_all_brands': show_all_brands,
        'brand': brand,
        'querystring': request.GET.urlencode(),
    })


@staff_member_required
@require_POST
def lead_status_flip(request, pk):
    """Operator mirror control (Affiliate Inbound API spec §7's "manually
    flip status in testing"): apply_status_change with source=operator.
    Works from the Leads console's per-lead panel — see leads.html. An
    override_reason is required (and only meaningful) once the lead's
    (affiliate, offer) pair is LIVE — see leadgen.status_sync's own
    TESTING/LIVE rule; this view just surfaces StatusAuthorityError as a
    normal message instead of a 500 when the operator forgets one."""
    leads_qs, _, _ = _scoped_leads(request)
    lead = get_object_or_404(leads_qs, pk=pk)

    to_status = request.POST.get('to_status')
    if to_status not in canonical_status.VALUES:
        messages.error(request, 'Select a valid status.')
        return redirect(_leads_redirect_url(request))

    override_reason = (request.POST.get('override_reason') or '').strip()
    try:
        apply_status_change(
            lead, to_status, source=LeadStatusEvent.SOURCE_OPERATOR,
            actor=request.user, override_reason=override_reason,
        )
    except StatusAuthorityError as exc:
        messages.error(request, str(exc))
        return redirect(_leads_redirect_url(request))

    messages.success(request, f'Lead #{lead.pk} status set to {to_status}.')
    return redirect(_leads_redirect_url(request))


def _scoped_affiliate_offer_links(request):
    show_all_brands = sees_all_brands(request.user)
    brand = scope_brand(request)
    qs = AffiliateOfferLink.objects.select_related('affiliate', 'offer', 'phase_changed_by')
    if not show_all_brands:
        qs = qs.filter(offer__brand=brand)
    return qs.order_by('-updated_at'), brand, show_all_brands


@staff_member_required
def affiliate_offer_links_list(request):
    """Operator mirror control (spec §7): every (affiliate, offer) pair's
    testing/live phase, with a Go live / Revert to testing action.
    Postback delivery history is deliberately NOT rebuilt here — Django
    admin's existing PostbackDeliveryAdmin (leadgen/admin.py) already lists/
    filters/searches it well; this page links out to that rather than
    duplicating it."""
    links, brand, show_all_brands = _scoped_affiliate_offer_links(request)
    return render(request, 'leadgen/console/affiliate_offer_links.html', {
        'shell_role': 'admin',
        'page_title': 'Affiliate Integrations',
        'links': links,
        'show_all_brands': show_all_brands,
        'brand': brand,
    })


@staff_member_required
@require_POST
def affiliate_offer_link_go_live(request, pk):
    links, _, _ = _scoped_affiliate_offer_links(request)
    link = get_object_or_404(links, pk=pk)
    go_live(link, actor=request.user)
    messages.success(request, f'{link.affiliate} × {link.offer} is now LIVE.')
    return redirect('leadgen_console:affiliate_offer_links')


@staff_member_required
@require_POST
def affiliate_offer_link_revert(request, pk):
    links, _, _ = _scoped_affiliate_offer_links(request)
    link = get_object_or_404(links, pk=pk)
    revert_to_testing(link, actor=request.user)
    messages.success(request, f'{link.affiliate} × {link.offer} reverted to TESTING.')
    return redirect('leadgen_console:affiliate_offer_links')


@staff_member_required
@require_POST
def route_now(request):
    """Deliberately trigger leadgen.failover.advance_chain for one or more
    leads — queues the next untried buyer in each lead's resolved chain
    (async, same as every other background delivery in this app); results
    show up in the console/admin as the worker processes them, not
    inline. Brand-scoped: an operator can only route their own leads."""
    from .failover import advance_chain

    leads_qs, _, _ = _scoped_leads(request)
    lead_ids = request.POST.getlist('lead_ids')
    leads = list(leads_qs.filter(pk__in=lead_ids))

    if not leads:
        messages.error(request, 'Select at least one lead to route.')
        return redirect(_leads_redirect_url(request))

    for lead in leads:
        advance_chain(lead.pk)

    messages.success(
        request,
        f'Routing started for {len(leads)} lead(s) — refresh in a moment to see results.',
    )
    return redirect(_leads_redirect_url(request))


def _leads_redirect_url(request):
    qs = request.POST.get('querystring', '')
    url = reverse('leadgen_console:leads')
    return f'{url}?{qs}' if qs else url


@staff_member_required
def buyers_list(request):
    buyers, brand, show_all_brands = _scoped_buyers(request)
    buyers = list(buyers)
    return render(request, 'leadgen/console/buyers_list.html', {
        'shell_role': 'admin',
        'page_title': 'Buyers',
        'buyers': buyers,
        'show_all_brands': show_all_brands,
        'brand': brand,
        'health': _buyer_health(brand, show_all_brands=show_all_brands),
        'active_buyers': sum(1 for b in buyers if b.is_active),
        'auto_inject_buyers': sum(1 for b in buyers if b.auto_inject),
    })


def _injection_window(brand, *, show_all_brands, days=1):
    """Injections in the trailing window, brand-scoped through the lead.

    ``LeadInjection`` has no brand of its own — a buyer is brand-owned and the
    lead carries the brand — so scoping goes through ``lead__brand`` rather
    than a column on the injection itself.
    """
    since = timezone.now() - datetime.timedelta(days=days)
    qs = LeadInjection.objects.filter(created_at__gte=since)
    if not show_all_brands:
        qs = qs.filter(lead__brand=brand)
    return qs


def _delivery_latency(qs):
    """Mean wall time from injection created to delivered, in milliseconds.

    Derived from the two timestamps the model already keeps rather than a
    stored duration — there is no latency column, and adding one would mean a
    migration plus a write on a hot path for a number this can compute.
    Rows that never delivered are excluded: counting them as zero would make a
    dead buyer look like the fastest one on the page.
    """
    delivered = qs.filter(delivered_at__isnull=False)
    row = delivered.annotate(
        latency=ExpressionWrapper(F('delivered_at') - F('created_at'), output_field=DurationField())
    ).aggregate(avg=Avg('latency'))
    avg = row['avg']
    if avg is None:
        return None
    return int(avg.total_seconds() * 1000)


def _buyer_health(brand, *, show_all_brands):
    """Delivery quality across buyers for the last 24 hours.

    Accept rate and latency are real, derived numbers. Note there is no cap
    utilisation here: LeadBuyer has no daily/hourly cap or concurrency field —
    throughput is governed by the token-bucket rate limit
    (rate_limit_burst / refill) and batch_max_size instead.
    """
    qs = _injection_window(brand, show_all_brands=show_all_brands)
    total = qs.count()
    delivered = qs.filter(status=LeadInjection.STATUS_DELIVERED).count()
    failed = qs.filter(status=LeadInjection.STATUS_FAILED).count()
    duplicate = qs.filter(status=LeadInjection.STATUS_DUPLICATE).count()
    pending = qs.filter(status=LeadInjection.STATUS_PENDING).count()

    return {
        'total': total,
        'delivered': delivered,
        'accept_rate': charts.meter(delivered, total, tone='teal'),
        'latency_ms': _delivery_latency(qs),
        'retrying': qs.filter(next_retry_at__isnull=False).count(),
        'outcomes': charts.donut([
            ('Delivered', delivered, 'pos'),
            ('Pending', pending, 'warn'),
            ('Duplicate', duplicate, 'muted'),
            ('Failed', failed, 'neg'),
        ]),
    }


def _routing_stats(brand, *, show_all_brands):
    """What routing actually did in the last 24 hours.

    "Matched" is leads that reached at least one buyer, against every lead
    taken in — the complement is the four terminal states the Lead model keeps
    deliberately separate (unrouted / held / exhausted / quarantined), so a
    low number here points at a real configuration gap rather than noise.
    """
    since = timezone.now() - datetime.timedelta(days=1)

    leads = Lead.objects.filter(created_at__gte=since)
    if not show_all_brands:
        leads = leads.filter(brand=brand)

    injections = _injection_window(brand, show_all_brands=show_all_brands)
    delivered = injections.filter(status=LeadInjection.STATUS_DELIVERED)

    leads_total = leads.count()
    leads_matched = leads.filter(injections__isnull=False).distinct().count()

    # A "fallback" is a lead the first buyer did not take, so routing moved
    # down the waterfall — i.e. more than one injection exists for it.
    fallbacks = (
        leads.annotate(n=Count('injections'))
        .filter(n__gt=1)
        .count()
    )

    by_buyer = list(
        delivered.values('buyer__name')
        .annotate(n=Count('id'))
        .order_by('-n')[:6]
    )

    return {
        'distributed': delivered.count(),
        'matched': charts.meter(leads_matched, leads_total, tone='blue'),
        'matched_text': f'{leads_matched} / {leads_total}',
        'latency_ms': _delivery_latency(injections),
        'fallbacks': fallbacks,
        'by_buyer': charts.bar_chart([(r['buyer__name'], r['n']) for r in by_buyer]),
    }


@staff_member_required
def lead_detail(request, pk):
    """One lead, its routing journey, and its status history.

    The journey is two things side by side, and conflating them hides real
    faults: the chain routing WOULD take for this lead right now
    (``resolve_buyer_chain``, recomputed live from the active rules) and what
    it actually DID (its LeadInjection rows, in order). A lead sitting in
    `unrouted` with a non-empty planned chain means the rules changed after
    the fact; an empty planned chain means nothing is configured to take it.

    Deliberately does not render ``LeadInjection.request_payload`` or
    ``response_payload``. Responses are filtered default-deny by
    ``sanitize_response_for_audit`` at write time, but rows written before
    that landed can still hold a buyer credential (Hypernet's redirectUrl is
    an autologin bearer URL), and a lead also carries an encrypted broker
    password and redirect. The derived outcome fields below answer the
    operator's question without putting any of that on screen.
    """
    leads, brand, show_all_brands = _scoped_leads(request)
    lead = get_object_or_404(leads, pk=pk)

    injections = list(
        lead.injections.select_related('buyer').order_by('created_at', 'id')
    )
    for injection in injections:
        if injection.delivered_at:
            delta = injection.delivered_at - injection.created_at
            injection.latency_ms = int(delta.total_seconds() * 1000)
        else:
            injection.latency_ms = None

    attempted_buyer_ids = {i.buyer_id for i in injections}
    planned = resolve_buyer_chain(lead)

    return render(request, 'leadgen/console/lead_detail.html', {
        'shell_role': 'admin',
        'page_title': f'Lead #{lead.pk}',
        'lead': lead,
        'brand': brand,
        'show_all_brands': show_all_brands,
        'injections': injections,
        'planned_chain': [
            {'buyer': buyer, 'attempted': buyer.pk in attempted_buyer_ids}
            for buyer in planned
        ],
        'status_events': lead.status_events.select_related('actor').order_by('-lead_seq')[:20],
        'delivered_to': next(
            (i for i in injections if i.status == LeadInjection.STATUS_DELIVERED), None
        ),
    })


def mappable_field_sources():
    """Every source name the field-mapping editor offers, in one list.

    Three groups, deliberately in this order — always-sent core first, then
    the opt-in sources that only reach a buyer because a mapping names them
    (connectors.OPT_IN_LEAD_FIELDS):

      firstname, lastname, ...      the MAPPABLE_LEAD_FIELDS core
      language                      Lead.language
      attribution.funnel, ...       the canonical Lead.attribution keys

    Only the CANONICAL attribution keys are listed. An affiliate's `extra`
    keys are open-ended by design, so no fixed list can enumerate them — the
    editor keeps any key already present in a saved mapping (see
    buildFieldOptions in buyer_form.html), which is how a brand points
    'attribution.risk_band' at MPC_6 and has it survive the next edit.
    """
    return (
        list(MAPPABLE_LEAD_FIELDS.keys())
        + list(OPT_IN_LEAD_FIELDS.keys())
        + [ATTRIBUTION_SOURCE_PREFIX + key for key in ATTRIBUTION_FIELDS + SUB_FIELDS]
    )


def _buyer_form_context(*, page_title, form, instance, test_result=None):
    """Shared context for buyer_form/buyer_test_connection — both render
    leadgen/console/buyer_form.html and both need the same BoxType-defaults
    + mappable-field-names data for the field-mapping editor (see
    buyer_form.html's <script>), so it's built in one place rather than
    duplicated per view."""
    return {
        'shell_role': 'admin',
        'page_title': page_title,
        'form': form,
        'instance': instance,
        'box_type_defaults_json': json.dumps({
            str(bt.pk): bt.default_field_mapping for bt in BoxType.objects.all()
        }),
        'mappable_lead_fields_json': json.dumps(mappable_field_sources()),
        'test_result': test_result,
    }


@staff_member_required
def buyer_form(request, pk=None):
    show_all_brands = sees_all_brands(request.user)
    brand = scope_brand(request)
    restrict_to_brand = None if show_all_brands else brand

    instance = None
    if pk is not None:
        qs, _, _ = _scoped_buyers(request)
        instance = get_object_or_404(qs, pk=pk)

    if request.method == 'POST':
        form = LeadBuyerForm(request.POST, instance=instance, restrict_to_brand=restrict_to_brand)
        if form.is_valid():
            saved = form.save()
            messages.success(request, f'Buyer "{saved.name}" saved.')
            return redirect('leadgen_console:buyers')
    else:
        form = LeadBuyerForm(instance=instance, restrict_to_brand=restrict_to_brand)

    return render(request, 'leadgen/console/buyer_form.html', _buyer_form_context(
        page_title='Edit Buyer' if instance else 'Add Buyer', form=form, instance=instance))


@staff_member_required
@require_POST
def buyer_test_connection(request, pk):
    """Send one synthetic, obviously-fake lead through the buyer's real
    connector and show the raw request payload + response (or error)
    inline — build guide Phase 5's "trivial onboarding" ask: confirm a
    freshly configured buyer's auth/field-mapping/endpoint actually work
    before flipping auto_inject on, without needing a real consumer lead
    or shell access. Deliberately does NOT create a Lead or LeadInjection
    row — this is a connectivity check, not a real delivery, and must
    never show up in the leads console, routing stats, or billing.
    Tests the currently SAVED configuration, not unsaved form edits — the
    submitted POST body (any in-progress edits) is intentionally ignored,
    see buyer_form.html's Test Connection button."""
    qs, _, _ = _scoped_buyers(request)
    instance = get_object_or_404(qs, pk=pk)

    test_lead = Lead(
        first_name='Nexora', last_name='TestConnection',
        email='nexora-test-connection@example.invalid',
        phone='+10000000000', vertical='test',
        source_id=f'test-connection-{instance.slug}',
    )

    test_result = {'payload': None, 'response': None, 'error': None}
    try:
        connector = get_connector(instance)
        test_result['payload'] = connector.build_payload(test_lead)
        test_result['response'] = connector.inject_lead(test_lead)
    except LeadBuyerError as exc:
        test_result['error'] = str(exc)
    except Exception as exc:  # noqa: BLE001 — surface any config error (e.g. missing box_type) to the operator, not a 500
        test_result['error'] = f'{exc.__class__.__name__}: {exc}'

    form = LeadBuyerForm(
        instance=instance, restrict_to_brand=None if sees_all_brands(request.user) else scope_brand(request))
    return render(request, 'leadgen/console/buyer_form.html', _buyer_form_context(
        page_title='Edit Buyer', form=form, instance=instance, test_result=test_result))


@staff_member_required
def routing_rules_list(request):
    show_all_brands = sees_all_brands(request.user)
    brand = scope_brand(request)
    qs = RoutingRule.objects.select_related('brand', 'buyer', 'offer', 'affiliate').order_by('priority', 'id')
    if not show_all_brands:
        qs = qs.filter(brand=brand)

    # Counts are taken before filtering: the header describes the rule set, not
    # the current view of it, so narrowing the table doesn't make it look like
    # rules disappeared.
    total_rules = qs.count()
    active_rules = qs.filter(is_active=True).count()

    verticals = sorted(v for v in qs.exclude(vertical='').values_list('vertical', flat=True).distinct())
    buyers_for_filter, _, _ = _scoped_buyers(request)

    selected = {
        'vertical': request.GET.get('vertical', ''),
        'buyer': request.GET.get('buyer', ''),
        'status': request.GET.get('status', ''),
        'q': request.GET.get('q', '').strip(),
    }

    if selected['vertical']:
        qs = qs.filter(vertical=selected['vertical'])
    if selected['buyer'].isdigit():
        qs = qs.filter(buyer_id=selected['buyer'])
    if selected['status'] == 'active':
        qs = qs.filter(is_active=True)
    elif selected['status'] == 'paused':
        qs = qs.filter(is_active=False)
    if selected['q']:
        qs = qs.filter(Q(name__icontains=selected['q']) | Q(buyer__name__icontains=selected['q']))

    return render(request, 'leadgen/console/routing_rules_list.html', {
        'shell_role': 'admin',
        'page_title': 'Routing Rules',
        'rules': qs,
        'show_all_brands': show_all_brands,
        'brand': brand,
        'total_rules': total_rules,
        'active_rules': active_rules,
        'paused_rules': total_rules - active_rules,
        'verticals': verticals,
        'buyers_for_filter': buyers_for_filter,
        'selected': selected,
        'is_filtered': any(selected.values()),
        'stats': _routing_stats(brand, show_all_brands=show_all_brands),
    })


@staff_member_required
def routing_rule_form(request, pk=None):
    show_all_brands = sees_all_brands(request.user)
    brand = scope_brand(request)
    restrict_to_brand = None if show_all_brands else brand

    instance = None
    if pk is not None:
        qs = RoutingRule.objects.all()
        if not show_all_brands:
            qs = qs.filter(brand=brand)
        instance = get_object_or_404(qs, pk=pk)

    if request.method == 'POST':
        form = RoutingRuleForm(request.POST, instance=instance, restrict_to_brand=restrict_to_brand)
        if form.is_valid():
            saved = form.save()
            messages.success(request, f'Routing rule "{saved}" saved.')
            return redirect('leadgen_console:routing_rules')
    else:
        form = RoutingRuleForm(instance=instance, restrict_to_brand=restrict_to_brand)

    return render(request, 'leadgen/console/routing_rule_form.html', {
        'shell_role': 'admin',
        'page_title': 'Edit Routing Rule' if instance else 'Add Routing Rule',
        'form': form,
        'instance': instance,
    })
