"""Affiliate-facing 'My Leads' page at /partner/leads/ — an affiliate can see
every lead they've submitted (either channel) and manually inject any of
their own leads to a configured buyer.

Ownership is enforced server-side (Lead.objects.filter(..., affiliate=
request.user)) on the inject endpoint, not just hidden in the UI — a direct
POST with someone else's lead id must not be able to inject it."""
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from affiliate_ui.gates import require_approved_affiliate
from impersonation.decorators import block_when_impersonating
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
