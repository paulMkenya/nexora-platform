"""Affiliate-facing payout views at /partner/payouts/."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from payouts.crypto.validators import SUPPORTED_NETWORKS, validate_address
from payouts.models import (
    METHOD_CHOICES, METHOD_CRYPTO, PayoutMethod, PayoutRequest,
    PayoutSettings, STATUS_PENDING, SCHEDULE_CHOICES,
)
from payouts.services import get_or_create_payout_settings, get_unpaid_earnings

from datetime import date, timedelta


@login_required
def payouts_home(request):
    methods = PayoutMethod.objects.filter(affiliate=request.user)
    requests_qs = PayoutRequest.objects.filter(affiliate=request.user).select_related('payout_method')[:50]
    ps = get_or_create_payout_settings(request.user)

    today = date.today()
    paid_through = ps.paid_through or date(2000, 1, 1)
    pending_earnings = get_unpaid_earnings(request.user, paid_through + timedelta(days=1), today)

    ctx = {
        'methods': methods,
        'payout_requests': requests_qs,
        'settings': ps,
        'pending_earnings': pending_earnings,
        'method_choices': METHOD_CHOICES,
        'schedule_choices': SCHEDULE_CHOICES,
        'supported_networks': SUPPORTED_NETWORKS,
    }
    return render(request, 'payouts/affiliate_payouts.html', ctx)


@login_required
@require_POST
def add_payout_method(request):
    method = request.POST.get('method', '').strip()
    valid_methods = {k for k, _ in METHOD_CHOICES}
    if method not in valid_methods:
        return HttpResponseBadRequest('Invalid method')

    details = {}
    if method == METHOD_CRYPTO:
        network = request.POST.get('network', '').strip()
        wallet_address = request.POST.get('wallet_address', '').strip()
        asset = request.POST.get('asset', network).strip()
        if not validate_address(network, wallet_address):
            messages.error(request, f'Invalid wallet address for {network}')
            return redirect('affiliate_ui:payouts')
        details = {'network': network, 'wallet_address': wallet_address, 'asset': asset}
    elif method == 'mpesa':
        details = {'phone': request.POST.get('phone', '').strip()}
    elif method in ('paypal', 'paxum'):
        details = {'email': request.POST.get('email', '').strip()}
    elif method == 'wise':
        details = {
            'email': request.POST.get('email', '').strip(),
            'recipient_id': request.POST.get('recipient_id', '').strip(),
        }
    elif method == 'bank':
        details = {
            'bank_name': request.POST.get('bank_name', '').strip(),
            'account_number': request.POST.get('account_number', '').strip(),
            'routing': request.POST.get('routing', '').strip(),
            'swift': request.POST.get('swift', '').strip(),
        }

    is_default = request.POST.get('is_default') == '1'
    PayoutMethod.objects.create(
        affiliate=request.user,
        method=method,
        details=details,
        is_default=is_default,
    )
    messages.success(request, 'Payout method added.')
    return redirect('affiliate_ui:payouts')


@login_required
@require_POST
def delete_payout_method(request, pk):
    pm = get_object_or_404(PayoutMethod, pk=pk, affiliate=request.user)
    pm.delete()
    messages.success(request, 'Payout method removed.')
    return redirect('affiliate_ui:payouts')


@login_required
@require_POST
def set_default_method(request, pk):
    pm = get_object_or_404(PayoutMethod, pk=pk, affiliate=request.user)
    pm.is_default = True
    pm.save()
    return redirect('affiliate_ui:payouts')


@login_required
@require_POST
def request_early_payout(request):
    ps = get_or_create_payout_settings(request.user)
    today = date.today()
    paid_through = ps.paid_through or date(2000, 1, 1)
    earnings = get_unpaid_earnings(request.user, paid_through + timedelta(days=1), today)

    if earnings < ps.min_threshold:
        messages.error(request, f'Earnings ${earnings:.2f} below threshold ${ps.min_threshold:.2f}')
        return redirect('affiliate_ui:payouts')

    from payouts.models import PayoutRequest
    from django.db import transaction

    period_start = paid_through + timedelta(days=1)
    period_end = today

    with transaction.atomic():
        ps_locked = PayoutSettings.objects.select_for_update().get(pk=ps.pk)
        if PayoutRequest.objects.filter(
            affiliate=request.user, period_start=period_start, period_end=period_end
        ).exists():
            messages.warning(request, 'A payout request already exists for this period.')
            return redirect('affiliate_ui:payouts')

        default_method = PayoutMethod.objects.filter(affiliate=request.user, is_default=True).first()
        PayoutRequest.objects.create(
            affiliate=request.user,
            payout_method=default_method,
            amount=earnings,
            currency='USD',
            method=default_method.method if default_method else 'paypal',
            status=STATUS_PENDING,
            period_start=period_start,
            period_end=period_end,
        )
        ps_locked.paid_through = period_end
        ps_locked.save(update_fields=['paid_through', 'updated_at'])

    messages.success(request, f'Payout request for ${earnings:.2f} submitted.')
    return redirect('affiliate_ui:payouts')


@login_required
@require_POST
def update_payout_settings(request):
    ps = get_or_create_payout_settings(request.user)
    schedule = request.POST.get('schedule', ps.schedule)
    valid_schedules = {k for k, _ in SCHEDULE_CHOICES}
    if schedule in valid_schedules:
        ps.schedule = schedule
    ps.save(update_fields=['schedule', 'updated_at'])
    messages.success(request, 'Payout settings updated.')
    return redirect('affiliate_ui:payouts')


@login_required
def validate_address_api(request):
    """AJAX endpoint for live address validation in the UI."""
    network = request.GET.get('network', '')
    address = request.GET.get('address', '')
    valid = validate_address(network, address)
    return JsonResponse({'valid': valid})


@login_required
def fee_estimate_api(request):
    """AJAX endpoint to get fee estimate for a network."""
    from payouts.providers.dispatch import get_crypto_provider
    network = request.GET.get('network', '')
    amount = float(request.GET.get('amount', '0') or '0')
    try:
        provider = get_crypto_provider()
        fee = provider.estimate_fee(network, amount) if provider.is_enabled() else None
    except Exception:
        fee = None
    return JsonResponse({'fee_estimate': fee or 'Provider not configured'})
