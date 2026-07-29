"""The Distribution console (Phase 3 of the lead-distribution build) — a
purpose-built, shared-shell surface for the leads inbox, buyer roster, and
routing rules, replacing the raw table that used to sit bolted under the
operator dashboard. Django admin (leadgen/admin.py) stays available as the
power-user fallback and test surface — this console is the primary one.

Every view here is brand-scoped exactly like brands.views.admin_views.
dashboard: a superuser (platform owner) sees/acts across every brand, an
ordinary operator only ever sees/touches their own."""
import json

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import get_user_model
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from brands.scoping import scope_brand, sees_all_brands

from .connectors import MAPPABLE_LEAD_FIELDS, LeadBuyerError, get_connector
from .forms import LeadBuyerForm, RoutingRuleForm
from .models import BoxType, Lead, LeadBuyer, RoutingRule
from .routing import attach_computed_chains
from .services import attach_latest_injections

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
        qs = qs.filter(Q(brand=brand) | Q(brand__isnull=True))
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
        'show_all_brands': show_all_brands,
        'brand': brand,
        'querystring': request.GET.urlencode(),
    })


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
    return render(request, 'leadgen/console/buyers_list.html', {
        'shell_role': 'admin',
        'page_title': 'Buyers',
        'buyers': buyers,
        'show_all_brands': show_all_brands,
        'brand': brand,
    })


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
        'mappable_lead_fields_json': json.dumps(list(MAPPABLE_LEAD_FIELDS.keys())),
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
    return render(request, 'leadgen/console/routing_rules_list.html', {
        'shell_role': 'admin',
        'page_title': 'Routing Rules',
        'rules': qs,
        'show_all_brands': show_all_brands,
        'brand': brand,
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
