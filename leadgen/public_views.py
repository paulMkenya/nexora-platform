"""Public, unauthenticated lead-capture page — one per Offer, for direct ad
traffic (FB/Google/etc.) landing straight on a Nexora-hosted funnel instead
of going through an affiliate's own site.

Same threat model as platform_leads.get_started (public form exposed to
bots/scrapers), so it reuses that exact proven shape: a honeypot field no
human fills, and a per-IP rate limit backed by the cache that fails OPEN
(never blocks a genuine submission because the cache happens to be down).
"""
import logging

from django.core.cache import cache
from django.shortcuts import get_object_or_404, render

from offer.models import Offer

from .models import Lead
from .serializers import LeadSubmitSerializer
from .tasks import maybe_auto_inject

logger = logging.getLogger(__name__)

RATE_LIMIT_MAX = 5            # submissions ...
RATE_LIMIT_WINDOW = 60 * 60   # ... per this many seconds (1 hour), per IP


def _client_ip(request):
    xff = request.META.get('HTTP_X_FORWARDED_FOR', '')
    if xff:
        return xff.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '') or 'unknown'


def _rate_limited(request):
    key = f'leadgen_capture_rl:{_client_ip(request)}'
    try:
        added = cache.add(key, 1, RATE_LIMIT_WINDOW)
        count = 1 if added else cache.incr(key)
    except Exception:  # noqa: BLE001 — cache down: fail open, never block a real lead
        logger.warning('Rate-limit cache unavailable; allowing submission', exc_info=True)
        return False
    return count > RATE_LIMIT_MAX


def capture_lead(request, offer_id):
    """GET renders the form; POST validates + creates the Lead."""
    offer = get_object_or_404(Offer, pk=offer_id)
    ctx = {'offer': offer, 'brand': offer.brand}

    if request.method != 'POST':
        return render(request, 'leadgen/capture_form.html', ctx)

    # Honeypot: a hidden field no human fills. A neutral, non-autofill name —
    # a field that LOOKS like a real contact field gets silently populated by
    # browser autofill and would drop genuine leads.
    if request.POST.get('hp_check', '').strip():
        logger.info('Honeypot tripped on leadgen capture (offer=%s) from ip=%s', offer_id, _client_ip(request))
        ctx['submitted'] = True
        return render(request, 'leadgen/capture_form.html', ctx)

    if _rate_limited(request):
        ctx['rate_limited'] = True
        return render(request, 'leadgen/capture_form.html', ctx, status=429)

    serializer = LeadSubmitSerializer(data={
        'first_name': request.POST.get('first_name', ''),
        'last_name': request.POST.get('last_name', ''),
        'email': request.POST.get('email', ''),
        'phone': request.POST.get('phone', ''),
        'vertical': request.POST.get('vertical', ''),
        'source_id': request.POST.get('source_id', ''),
    })
    if not serializer.is_valid():
        ctx['errors'] = serializer.errors
        ctx['post'] = request.POST
        return render(request, 'leadgen/capture_form.html', ctx, status=400)

    data = serializer.validated_data
    lead = Lead.objects.create(
        brand=offer.brand,
        intake_channel=Lead.CHANNEL_LANDING_PAGE,
        affiliate=None,
        offer=offer,
        first_name=data['first_name'],
        last_name=data['last_name'],
        email=data['email'],
        phone=data['phone'],
        vertical=data['vertical'],
        source_id=data['source_id'],
        ip=_client_ip(request),
        raw_payload=data,
    )
    maybe_auto_inject(lead)

    ctx['submitted'] = True
    return render(request, 'leadgen/capture_form.html', ctx)
