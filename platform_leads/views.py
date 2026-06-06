"""Platform sales funnel views.

Two distinct surfaces:

  * **Public** ``/get-started/`` — the lead-capture form. Brand-aware styling but
    it is the *platform's* own funnel. Honeypot + per-IP rate limiting guard the
    POST endpoint. A submit creates a ``PlatformLead`` and fires the owner alert.

  * **Owner-only** ``/admin/platform-leads/…`` — the sales pipeline. STRICTLY
    superuser-only (``platform_owner_required``): brand admins, affiliate
    managers and anonymous users get 403 (and the nav link is hidden from them).
    Sales stages are MANUAL — the owner moves a lead to any stage by hand.
"""
import logging

from django.contrib import messages
from django.core.cache import cache
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from brands.models import Brand
from brands.permissions import platform_owner_required
from offer.models import Category, TrafficSource
from platform_leads.models import PlatformLead
from platform_leads.tasks import enqueue_platform_lead_alert
from user_profile.geo import country_choices

logger = logging.getLogger(__name__)

# Per-IP rate limit on the public submit endpoint.
RATE_LIMIT_MAX = 5            # submissions ...
RATE_LIMIT_WINDOW = 60 * 60   # ... per this many seconds (1 hour)


def _client_ip(request):
    xff = request.META.get('HTTP_X_FORWARDED_FOR', '')
    if xff:
        return xff.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '') or 'unknown'


def _rate_limited(request):
    """True if this IP has exceeded the submit budget. Counts this attempt.

    Backed by the Django cache (Redis in prod, locmem locally). A cache outage
    fails open — we never block a genuine submission because the cache is down.
    """
    key = f'platform_lead_rl:{_client_ip(request)}'
    try:
        added = cache.add(key, 1, RATE_LIMIT_WINDOW)
        count = 1 if added else cache.incr(key)
    except Exception:  # noqa: BLE001 — cache down: fail open, never block a real lead
        logger.warning('Rate-limit cache unavailable; allowing submission', exc_info=True)
        return False
    return count > RATE_LIMIT_MAX


def _form_context(extra=None):
    ctx = {
        'lead_types': PlatformLead.LeadType.choices,
        'timelines': PlatformLead.Timeline.choices,
        'categories': Category.objects.order_by('name'),
        'traffic_sources': TrafficSource.objects.order_by('name'),
        'countries': country_choices(),
    }
    if extra:
        ctx.update(extra)
    return ctx


def get_started(request):
    """Public adaptive lead-capture form for the platform's own funnel."""
    if request.method != 'POST':
        return render(request, 'platform_leads/get_started.html', _form_context())

    # Honeypot: a hidden field no human fills. If present, silently accept
    # (return the same thank-you) without creating a record — don't tip off bots.
    if request.POST.get('company_url', '').strip():
        logger.info('Honeypot tripped on /get-started/ from ip=%s', _client_ip(request))
        return render(request, 'platform_leads/get_started.html',
                      _form_context({'submitted': True}))

    if _rate_limited(request):
        return render(request, 'platform_leads/get_started.html',
                      _form_context({'rate_limited': True}), status=429)

    errors = _validate_submission(request.POST)
    if errors:
        return render(request, 'platform_leads/get_started.html', _form_context({
            'errors': errors,
            # Re-fill what they typed so a validation bounce isn't punishing.
            'post': request.POST,
        }), status=400)

    lead = _create_lead(request.POST)
    enqueue_platform_lead_alert(lead.pk)

    return render(request, 'platform_leads/get_started.html',
                  _form_context({'submitted': True}))


def _validate_submission(post):
    """The three required fields (everything else is optional server-side)."""
    errors = []
    if post.get('lead_type', '').strip() not in {v for v, _ in PlatformLead.LeadType.choices}:
        errors.append('Please tell us what you are looking for.')
    if not post.get('name', '').strip():
        errors.append('Please enter your name.')
    if not post.get('email', '').strip():
        errors.append('Please enter your email so we can reach you.')
    return errors


def _create_lead(post):
    """Build a PlatformLead from validated POST data + its M2M selections."""
    timeline = post.get('timeline', '').strip()
    if timeline not in {v for v, _ in PlatformLead.Timeline.choices}:
        timeline = ''

    lead = PlatformLead.objects.create(
        lead_type=post.get('lead_type', '').strip(),
        name=post.get('name', '').strip(),
        email=post.get('email', '').strip(),
        phone=post.get('phone', '').strip(),
        company=post.get('company', '').strip(),
        country=post.get('country', '').strip()[:2].upper(),
        website=post.get('website', '').strip(),
        scale=post.get('scale', '').strip(),
        pain=post.get('pain', '').strip(),
        timeline=timeline,
        budget=post.get('budget', '').strip(),
        source=post.get('source', '').strip(),
    )

    # Multi-selects reuse the offer taxonomy (filtered to real ids).
    vert_ids = [v for v in post.getlist('verticals') if v.isdigit()]
    if vert_ids:
        lead.verticals.set(Category.objects.filter(id__in=vert_ids))
    ts_ids = [t for t in post.getlist('traffic_sources') if t.isdigit()]
    if ts_ids:
        lead.traffic_sources.set(TrafficSource.objects.filter(id__in=ts_ids))
    return lead


# ── Owner-only pipeline ──────────────────────────────────────────────────────


@platform_owner_required
def pipeline(request):
    """Owner-only sales funnel: list + per-stage summary + stage filter."""
    qs = PlatformLead.objects.prefetch_related('verticals', 'traffic_sources')

    stage_filter = request.GET.get('stage', '').strip()
    if stage_filter:
        qs = qs.filter(sales_stage=stage_filter)
    type_filter = request.GET.get('type', '').strip()
    if type_filter:
        qs = qs.filter(lead_type=type_filter)

    raw_counts = dict(
        PlatformLead.objects.values_list('sales_stage').annotate(n=Count('id')))
    stage_counts = [
        {'value': value, 'label': label, 'count': raw_counts.get(value, 0)}
        for value, label in PlatformLead.Stage.choices
    ]

    return render(request, 'platform_leads/admin/pipeline.html', {
        'active': 'platform_leads',
        'leads': qs,
        'stage_counts': stage_counts,
        'total_count': sum(c['count'] for c in stage_counts),
        'stage_filter': stage_filter,
        'type_filter': type_filter,
        'stage_choices': PlatformLead.Stage.choices,
        'type_choices': PlatformLead.LeadType.choices,
    })


@platform_owner_required
def lead_detail(request, pk):
    """Full detail of one platform lead (all captured fields)."""
    lead = get_object_or_404(
        PlatformLead.objects.prefetch_related('verticals', 'traffic_sources'), pk=pk)
    return render(request, 'platform_leads/admin/lead_detail.html', {
        'active': 'platform_leads',
        'lead': lead,
        'stage_choices': PlatformLead.Stage.choices,
    })


@platform_owner_required
@require_POST
def update_stage(request, pk):
    """Manual stage change — the owner may move a lead to any stage."""
    lead = get_object_or_404(PlatformLead, pk=pk)
    stage = request.POST.get('sales_stage', '').strip()
    if stage in {v for v, _ in PlatformLead.Stage.choices}:
        lead.sales_stage = stage
        lead.save(update_fields=['sales_stage'])
    return redirect(_back(request, pk))


@platform_owner_required
@require_POST
def add_note(request, pk):
    """Append a timestamped note."""
    lead = get_object_or_404(PlatformLead, pk=pk)
    note = request.POST.get('note', '').strip()
    if note:
        stamp = timezone.now().strftime('%Y-%m-%d %H:%M')
        entry = f'[{stamp}] {note}'
        lead.notes = (lead.notes + '\n' if lead.notes else '') + entry
        lead.save(update_fields=['notes'])
    return redirect(_back(request, pk))


@platform_owner_required
@require_POST
def mark_contacted(request, pk):
    """Stamp last_contact_at = now (the owner just reached out)."""
    lead = get_object_or_404(PlatformLead, pk=pk)
    lead.last_contact_at = timezone.now()
    lead.save(update_fields=['last_contact_at'])
    return redirect(_back(request, pk))


@platform_owner_required
def settings_view(request):
    """Owner-only: set where sales-funnel alerts are emailed.

    Stored on the default brand's ``owner_sales_notification_email`` — NOT an env
    var — so the owner changes the destination without a redeploy.
    """
    brand = Brand.get_default()
    if request.method == 'POST':
        if brand is not None:
            brand.owner_sales_notification_email = (
                request.POST.get('owner_sales_notification_email', '').strip())
            brand.save(update_fields=['owner_sales_notification_email'])
            messages.success(request, 'Sales notification address saved.')
        return redirect('platform_leads_admin:settings')
    return render(request, 'platform_leads/admin/settings.html', {
        'active': 'platform_leads',
        'brand': brand,
        'current': brand.owner_sales_notification_email if brand else '',
        'resolved': Brand.owner_sales_recipient(),
    })


def _back(request, pk):
    """Return to the page the action came from (whitelisted), else the detail."""
    nxt = request.POST.get('next', '')
    if nxt.startswith('/admin/platform-leads/'):
        return nxt
    return f'/admin/platform-leads/{pk}/'
