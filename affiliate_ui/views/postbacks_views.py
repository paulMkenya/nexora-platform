"""Affiliate-facing Postbacks config page — Affiliate Inbound API spec
Phase 6 (§7): "register/edit postback URLs, see delivery log, choose which
statuses fire, view HMAC secret." Reuses AffiliatePostbackConfig directly
(the model built in Phase 4) — this is the self-service UI on top of what
was previously Django-admin-only.

Phase 7 hardening: postback_create/postback_update validate the URL through
leadgen.security.validate_postback_url before it's ever saved — an approved
affiliate is still an external party, and without this check they could
point the server's own worker at an internal service (see leadgen/security.py
for the full rationale). AffiliatePostbackConfig.clean() enforces the same
check for the Django admin path; this view uses raw request.POST, not a
ModelForm, so it needs its own explicit call to get a friendly inline error
instead of a 500 from full_clean() never running."""
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from affiliate_ui.gates import require_approved_affiliate
from impersonation.decorators import block_when_impersonating
from leadgen import canonical_status
from leadgen.models import AffiliatePostbackConfig
from leadgen.security import UnsafePostbackURLError, validate_postback_url


@require_approved_affiliate
def postbacks(request):
    configs = AffiliatePostbackConfig.objects.filter(affiliate=request.user).prefetch_related('deliveries')
    for config in configs:
        config.recent_deliveries = list(config.deliveries.all()[:10])
    return render(request, 'affiliate_ui/postbacks.html', {
        'configs': configs,
        'all_statuses': canonical_status.CHOICES,
    })


@block_when_impersonating
@require_approved_affiliate
@require_POST
def postback_create(request):
    url = (request.POST.get('url') or '').strip()
    if not url:
        messages.error(request, 'A postback URL is required.')
        return redirect('affiliate_ui:postbacks')
    try:
        validate_postback_url(url)
    except UnsafePostbackURLError as exc:
        messages.error(request, str(exc))
        return redirect('affiliate_ui:postbacks')
    subscribed = request.POST.getlist('subscribed_statuses')
    config = AffiliatePostbackConfig.objects.create(
        affiliate=request.user, url=url, subscribed_statuses=subscribed)
    messages.success(
        request,
        f'Postback created. Secret (shown once — copy it now): <code>{config.secret}</code>')
    return redirect('affiliate_ui:postbacks')


@block_when_impersonating
@require_approved_affiliate
@require_POST
def postback_update(request, pk):
    config = get_object_or_404(AffiliatePostbackConfig, pk=pk, affiliate=request.user)
    url = (request.POST.get('url') or '').strip()
    if not url:
        messages.error(request, 'A postback URL is required.')
        return redirect('affiliate_ui:postbacks')
    try:
        validate_postback_url(url)
    except UnsafePostbackURLError as exc:
        messages.error(request, str(exc))
        return redirect('affiliate_ui:postbacks')
    config.url = url
    config.subscribed_statuses = request.POST.getlist('subscribed_statuses')
    config.save(update_fields=['url', 'subscribed_statuses', 'updated_at'])
    messages.success(request, 'Postback updated.')
    return redirect('affiliate_ui:postbacks')


@block_when_impersonating
@require_approved_affiliate
@require_POST
def postback_toggle_active(request, pk):
    config = get_object_or_404(AffiliatePostbackConfig, pk=pk, affiliate=request.user)
    config.is_active = not config.is_active
    config.save(update_fields=['is_active', 'updated_at'])
    messages.success(request, f'Postback {"enabled" if config.is_active else "disabled"}.')
    return redirect('affiliate_ui:postbacks')
