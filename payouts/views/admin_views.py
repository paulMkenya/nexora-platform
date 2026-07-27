"""Network-admin payout views at /admin/payouts/."""
import csv
import io
import logging

from django.contrib.admin.views.decorators import staff_member_required
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from brands.scoping import is_platform_owner, scope_brand, sees_all_brands
from impersonation.decorators import block_when_impersonating
from payouts.models import (
    METHOD_CHOICES, PayoutBatch, PayoutRequest,
    STATUS_APPROVED, STATUS_BLOCKED, STATUS_PAID, STATUS_PENDING_APPROVAL,
)

logger = logging.getLogger(__name__)


def _scope_payouts(request, qs):
    """Confine a PayoutRequest queryset to the operator's own brand unless superuser.

    Payout requests carry no brand of their own; their brand is the affiliate's
    (Profile.brand). Brand-scoped operators only ever see/act on their own
    brand's requests — bound to the operator's assigned brand, not the request
    host, so the console can't be widened by visiting another brand's domain.
    Orphaned requests (affiliate without a brand) are excluded here and remain
    visible to superusers only.

    Archived affiliates are removed from the active payout surface entirely (for
    every operator, superuser included): their requests are hidden and cannot be
    acted on. The rows are retained in the database — archiving never destroys
    financial history — they simply drop off the active console.
    """
    qs = qs.exclude(affiliate__profile__is_archived=True)
    if sees_all_brands(request.user):
        return qs
    return qs.filter(affiliate__profile__brand=scope_brand(request))


@staff_member_required
def payout_list(request):
    status_filter = request.GET.get('status', '')
    provider_filter = request.GET.get('provider', '')

    qs = _scope_payouts(
        request,
        PayoutRequest.objects.select_related('affiliate', 'payout_method').order_by('-created_at'),
    )
    if status_filter:
        qs = qs.filter(status=status_filter)
    if provider_filter:
        qs = qs.filter(method=provider_filter)

    show_all_brands = sees_all_brands(request.user)
    if show_all_brands:
        orphans = PayoutRequest.objects.filter(affiliate__profile__brand__isnull=True).count()
        if orphans:
            logger.warning('payout_list: %s payout request(s) have no brand link', orphans)

    from payouts.models import REQUEST_STATUS_CHOICES
    ctx = {
        'requests': qs[:200],
        'status_filter': status_filter,
        'provider_filter': provider_filter,
        'status_choices': REQUEST_STATUS_CHOICES,
        'method_choices': METHOD_CHOICES,
        'show_all_brands': show_all_brands,
        'shell_role': 'admin',
        'page_title': 'Payouts',
    }
    return render(request, 'payouts/admin_payout_list.html', ctx)


@block_when_impersonating
@staff_member_required
@require_POST
def bulk_approve(request):
    ids = request.POST.getlist('ids')
    if not ids:
        return redirect('payouts_admin:payout_list')
    _scope_payouts(request, PayoutRequest.objects.filter(pk__in=ids, status__in=['pending'])).update(
        status=STATUS_APPROVED)
    return redirect('payouts_admin:payout_list')


@block_when_impersonating
@staff_member_required
@require_POST
def mark_paid(request):
    ids = request.POST.getlist('ids')
    if not ids:
        return redirect('payouts_admin:payout_list')
    tx_ref = request.POST.get('tx_ref', '')
    now = timezone.now()
    reqs = list(_scope_payouts(request, PayoutRequest.objects.filter(pk__in=ids)))
    for req in reqs:
        req.status = STATUS_PAID
        req.paid_at = now
        if tx_ref:
            req.tx_ref = tx_ref
    PayoutRequest.objects.bulk_update(reqs, ['status', 'paid_at', 'tx_ref', 'updated_at'])
    return redirect('payouts_admin:payout_list')


@block_when_impersonating
@staff_member_required
@require_POST
def dispatch_approved(request):
    """Dispatch approved payout requests through the withdrawal control layer.

    Every request passes through ``enforce_and_dispatch`` — the provider-agnostic
    safety net — at this single boundary: a payout is dispatched, blocked by a
    velocity limit, or parked in ``pending_approval`` (threshold / cool-down /
    anomaly). Nothing reaches a provider without being evaluated and audited.
    """
    from payouts.control import enforce_and_dispatch
    ids = request.POST.getlist('ids')
    qs = _scope_payouts(request, PayoutRequest.objects.filter(status=STATUS_APPROVED))
    if ids:
        qs = qs.filter(pk__in=ids)
    for req in qs.select_related('payout_method', 'affiliate__profile'):
        enforce_and_dispatch(req, actor=request.user)
    return redirect('payouts_admin:payout_list')


@staff_member_required
def download_batch_csv(request):
    """Download CSV of pending/approved requests grouped by provider."""
    provider = request.GET.get('provider', '')
    qs = _scope_payouts(request, PayoutRequest.objects.filter(
        status__in=[STATUS_APPROVED, 'pending']
    ).select_related('affiliate', 'payout_method'))
    if provider:
        qs = qs.filter(method=provider)

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(['ID', 'Affiliate', 'Method', 'Amount', 'Currency', 'Details', 'Status',
                     'Period Start', 'Period End'])
    for req in qs:
        details = req.payout_method.details if req.payout_method else {}
        writer.writerow([
            req.pk,
            req.affiliate.username,
            req.get_method_display(),
            req.amount,
            req.currency,
            str(details),
            req.status,
            req.period_start,
            req.period_end,
        ])

    label = f'_{provider}' if provider else ''
    filename = f'payouts{label}_{timezone.now().strftime("%Y%m%d")}.csv'
    response = HttpResponse(buf.getvalue(), content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'

    total = sum(req.amount for req in qs)
    batch = PayoutBatch.objects.create(
        provider=provider or 'mixed',
        total=total,
        csv_export=buf.getvalue(),
    )
    batch.requests.set(qs)
    return response


@staff_member_required
def batch_list(request):
    batches = PayoutBatch.objects.prefetch_related('requests').order_by('-created_at')[:50]
    return render(request, 'payouts/admin_batch_list.html', {
        'batches': batches, 'shell_role': 'admin', 'page_title': 'Payout Batches',
    })


# --- Withdrawal control layer: held-payouts review + config ----------------


@staff_member_required
def holds_list(request):
    """Operator view of payouts parked by the withdrawal control layer.

    Brand-scoped exactly like the main payout console (a brand operator only ever
    sees/acts on their own brand's held payouts; the platform owner sees all).
    Shows the latest control decision per request so the operator knows *why* it
    is held before acting.
    """
    qs = _scope_payouts(
        request,
        PayoutRequest.objects
        .filter(status__in=[STATUS_PENDING_APPROVAL, STATUS_BLOCKED])
        .select_related('affiliate', 'payout_method')
        .prefetch_related('decisions')
        .order_by('-updated_at'),
    )
    ctx = {
        'requests': qs[:200],
        'show_all_brands': sees_all_brands(request.user),
        'shell_role': 'admin',
        'page_title': 'Held Payouts',
    }
    return render(request, 'payouts/admin_holds_list.html', ctx)


@block_when_impersonating
@staff_member_required
@require_POST
def approve_hold(request, pk):
    """Approve a parked payout and dispatch it (audited)."""
    from payouts.control import approve
    req = _scope_payouts(
        request, PayoutRequest.objects.filter(pk=pk, status=STATUS_PENDING_APPROVAL)
    ).select_related('payout_method', 'affiliate__profile').first()
    if req is None:
        return redirect('payouts_admin:holds_list')
    reason = request.POST.get('reason', '')
    approve(req, request.user, reason=reason)
    return redirect('payouts_admin:holds_list')


@block_when_impersonating
@staff_member_required
@require_POST
def deny_hold(request, pk):
    """Deny a parked payout (audited; never dispatched)."""
    from payouts.control import deny
    req = _scope_payouts(
        request, PayoutRequest.objects.filter(pk=pk, status=STATUS_PENDING_APPROVAL)
    ).select_related('affiliate__profile').first()
    if req is None:
        return redirect('payouts_admin:holds_list')
    reason = request.POST.get('reason', '')
    deny(req, request.user, reason=reason)
    return redirect('payouts_admin:holds_list')


# Fields the owner edits on the global config and (nullable) per-brand override.
_GLOBAL_FIELDS = [
    'per_tx_max', 'per_affiliate_day_count', 'per_affiliate_day_amount',
    'per_brand_day_count', 'per_brand_day_amount',
    'platform_day_count', 'platform_day_amount', 'approval_threshold',
    'new_address_cooldown_hours', 'anomaly_multiple', 'anomaly_min_history',
    'anomaly_burst_count', 'anomaly_burst_window_minutes',
]
_DECIMAL_FIELDS = {
    'per_tx_max', 'per_affiliate_day_amount', 'per_brand_day_amount',
    'platform_day_amount', 'approval_threshold', 'anomaly_multiple',
}


@block_when_impersonating
@staff_member_required
def control_settings(request):
    """Owner-editable withdrawal-control configuration (NOT env-hardcoded).

    The platform-wide config is editable by the platform owner (superuser). The
    per-brand override is shown for the operator's own brand. Everything is stored
    in the database and read live by the control layer.
    """
    from decimal import Decimal, InvalidOperation
    from payouts.models import WithdrawalControlConfig

    cfg = WithdrawalControlConfig.load()
    is_owner = is_platform_owner(request.user)

    if request.method == 'POST' and is_owner:
        cfg.enabled = request.POST.get('enabled') == '1'
        for field in _GLOBAL_FIELDS:
            raw = request.POST.get(field, '').strip()
            if raw == '':
                continue
            try:
                value = Decimal(raw) if field in _DECIMAL_FIELDS else int(raw)
            except (InvalidOperation, ValueError):
                continue
            if value < 0:
                continue
            setattr(cfg, field, value)
        cfg.updated_by = request.user
        cfg.save()
        return redirect('payouts_admin:control_settings')

    ctx = {
        'cfg': cfg,
        'is_owner': is_owner,
        'fields': [(f, getattr(cfg, f)) for f in _GLOBAL_FIELDS],
        'shell_role': 'admin',
        'page_title': 'Withdrawal Controls',
    }
    return render(request, 'payouts/admin_control_settings.html', ctx)
