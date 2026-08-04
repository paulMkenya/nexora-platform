"""Affiliate-facing 'My Leads' page at /partner/leads/ — an affiliate can see
every lead they've submitted (either channel) and manually inject any of
their own leads to a configured buyer.

Ownership is enforced server-side (Lead.objects.filter(..., affiliate=
request.user)) on the inject endpoint, not just hidden in the UI — a direct
POST with someone else's lead id must not be able to inject it."""
from django.contrib import messages
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from affiliate_ui.gates import require_approved_affiliate
from impersonation.decorators import block_when_impersonating
from leadgen.models import Lead, LeadBuyer, LeadInjection
from leadgen.services import attach_latest_injections, inject_leads_to_buyer, summarize_injection_results
from leadgen.status_sync import attach_affiliate_phase


def _available_buyers(request):
    """Buyers a lead may be injected to.

    The `Q(brand=b) | Q(brand__isnull=True)` shape here looks identical to the
    offer-scoping fallback that was removed in favour of offers_for_affiliate,
    and it is deliberately NOT the same thing. The two models point in
    opposite directions:

      * `Brand` is an INBOUND tenant — its affiliates, its offers, its domain.
        A brandless *offer* reaching an affiliate exposes another tenant's
        inventory, so there is no fallback there: strict isolation.
      * `LeadBuyer` is an OUTBOUND destination — somewhere the routing engine
        sends leads. A brandless *buyer* plausibly means "a platform-level
        destination any inbound brand may route to", which is a routing
        decision, not a tenant leak.

    Same query pattern, opposite meaning, because inbound visibility and
    outbound routing are governed by different rules. Left exactly as-is
    pending Paul's separate ruling on outbound buyer scoping: is a brandless
    buyer reachable by ANY brand, or only by the platform brand? Until that is
    decided this is intentional, not a copied fallback.
    """
    brand = getattr(request, 'brand', None)
    return LeadBuyer.objects.filter(is_active=True).filter(
        Q(brand=brand) | Q(brand__isnull=True)).order_by('name')


@require_approved_affiliate
def my_leads(request):
    leads = list(Lead.objects.filter(affiliate=request.user).order_by('-created_at')[:200])
    attach_latest_injections(leads)
    attach_affiliate_phase(leads)
    return render(request, 'affiliate_ui/leads.html', {
        'leads': leads,
        'buyers': _available_buyers(request),
    })


@block_when_impersonating
@require_approved_affiliate
@require_POST
def inject_my_leads(request):
    buyer = get_object_or_404(_available_buyers(request), pk=request.POST.get('buyer_id'))
    lead_ids = request.POST.getlist('lead_ids')

    # Ownership scoping: only leads this affiliate actually submitted, even
    # if a lead_id for someone else's lead is included in the POST body.
    leads = list(Lead.objects.filter(pk__in=lead_ids, affiliate=request.user))
    if not leads:
        messages.error(request, 'Select at least one of your own leads.')
        return redirect('affiliate_ui:my_leads')

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
    return redirect('affiliate_ui:my_leads')
