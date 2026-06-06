"""Operator CRM pipeline view at /admin/leads/.

Brand-scoped via the shared ``brands.scoping`` helpers — the same single rule
used by payouts, fraud, affiliates and advertisers:

  * platform owner (superuser) → sees ALL brands' leads (+ a brand filter).
  * brand admin (NETWORK_ADMIN) → only their own brand's leads. Object-level:
    a cross-brand lead reached by direct ID is a 404, not a silent no-op.
  * affiliate managers           → blocked entirely (``brand_admin_required``).

Manual stage change + note editing is allowed here (the auto-advance is
forward-only; operators may move a lead anywhere by hand).
"""
import logging

from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from brands.models import Brand
from brands.permissions import brand_admin_required
from brands.scoping import scope_brand, sees_all_brands
from leads.models import Lead

logger = logging.getLogger(__name__)


def _scoped_leads(request):
    """Lead queryset visible to the current operator's role."""
    qs = Lead.objects.select_related('brand', 'profile__user', 'advertiser__user')
    if sees_all_brands(request.user):
        return qs
    return qs.filter(brand=scope_brand(request))


def _get_lead_or_404(request, pk):
    """Fetch a lead, 404 if outside the operator's brand scope."""
    return get_object_or_404(_scoped_leads(request), pk=pk)


@brand_admin_required
def lead_list(request):
    qs = _scoped_leads(request)

    owner = sees_all_brands(request.user)

    # Owner-only brand filter.
    brand_filter = request.GET.get('brand', '').strip()
    if owner and brand_filter:
        qs = qs.filter(brand_id=brand_filter)

    stage_filter = request.GET.get('stage', '').strip()
    if stage_filter:
        qs = qs.filter(pipeline_stage=stage_filter)

    type_filter = request.GET.get('type', '').strip()
    if type_filter:
        qs = qs.filter(lead_type=type_filter)

    # Per-stage counts honour the brand/type filters but not the stage filter,
    # so the summary always shows the full pipeline breakdown.
    count_base = _scoped_leads(request)
    if owner and brand_filter:
        count_base = count_base.filter(brand_id=brand_filter)
    if type_filter:
        count_base = count_base.filter(lead_type=type_filter)
    raw_counts = dict(
        count_base.values_list('pipeline_stage').annotate(n=Count('id'))
    )
    stage_counts = [
        {'value': value, 'label': label, 'count': raw_counts.get(value, 0)}
        for value, label in Lead.Stage.choices
    ]

    return render(request, 'leads/admin/lead_list.html', {
        'active': 'leads',
        'leads': qs,
        'stage_counts': stage_counts,
        'total_count': sum(c['count'] for c in stage_counts),
        'stage_filter': stage_filter,
        'type_filter': type_filter,
        'brand_filter': brand_filter,
        'stage_choices': Lead.Stage.choices,
        'type_choices': Lead.Type.choices,
        'sees_all_brands': owner,
        'brands': Brand.objects.all() if owner else Brand.objects.none(),
    })


@brand_admin_required
@require_POST
def lead_update_stage(request, pk):
    """Manual (operator) stage change — may move a lead to any stage."""
    lead = _get_lead_or_404(request, pk)
    stage = request.POST.get('pipeline_stage', '').strip()
    valid = {value for value, _ in Lead.Stage.choices}
    if stage in valid:
        lead.pipeline_stage = stage
        lead.save(update_fields=['pipeline_stage'])
    return redirect(_back(request))


@brand_admin_required
@require_POST
def lead_add_note(request, pk):
    """Append a note to a lead."""
    lead = _get_lead_or_404(request, pk)
    note = request.POST.get('note', '').strip()
    if note:
        lead.notes = (lead.notes + '\n' if lead.notes else '') + note
        lead.save(update_fields=['notes'])
    return redirect(_back(request))


def _back(request):
    nxt = request.POST.get('next', '')
    return nxt if nxt.startswith('/admin/leads/') else '/admin/leads/'
