"""Affiliate-facing Postbacks config page — Affiliate Inbound API spec
Phase 6 (§7): "register/edit postback URLs, see delivery log, choose which
statuses fire, view HMAC secret." Reuses AffiliatePostbackConfig directly
(the model built in Phase 4) — this is the self-service UI on top of what
was previously Django-admin-only."""
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from affiliate_ui.gates import require_approved_affiliate
from impersonation.decorators import block_when_impersonating
from leadgen import canonical_status
from leadgen.models import AffiliatePostbackConfig


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
