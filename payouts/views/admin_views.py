"""Network-admin payout views at /admin/payouts/."""
import csv
import io
import logging

from django.contrib.admin.views.decorators import staff_member_required
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from brands.scoping import scope_brand, sees_all_brands
from payouts.models import (
    METHOD_CHOICES, PayoutBatch, PayoutRequest,
    STATUS_APPROVED, STATUS_PAID,
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
    """
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
    }
    return render(request, 'payouts/admin_payout_list.html', ctx)


@staff_member_required
@require_POST
def bulk_approve(request):
    ids = request.POST.getlist('ids')
    if not ids:
        return redirect('payouts_admin:payout_list')
    _scope_payouts(request, PayoutRequest.objects.filter(pk__in=ids, status__in=['pending'])).update(
        status=STATUS_APPROVED)
    return redirect('payouts_admin:payout_list')


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


@staff_member_required
@require_POST
def dispatch_approved(request):
    """Dispatch all approved payout requests through their provider."""
    from payouts.providers.dispatch import dispatch_payout
    ids = request.POST.getlist('ids')
    qs = _scope_payouts(request, PayoutRequest.objects.filter(status=STATUS_APPROVED))
    if ids:
        qs = qs.filter(pk__in=ids)
    dispatched = 0
    for req in qs.select_related('payout_method'):
        dispatch_payout(req)
        req.save(update_fields=['status', 'tx_ref', 'notes', 'updated_at'])
        dispatched += 1
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
    return render(request, 'payouts/admin_batch_list.html', {'batches': batches})
