"""The single source of truth for an affiliate's personalized API
integration doc — Affiliate Inbound API spec §6. build_doc_context() is the
ONLY place that assembles this data; every render format (live HTML page,
PDF export, plain-text export) consumes the SAME dict, so they can never
drift from each other or from the real contract. Per spec §6.3: "rendered
from the SAME source of truth as the API itself... NEVER maintain the doc
as a separate static file."

Field rows are introspected directly off AffiliateLeadSubmitSerializer
(not hand-copied) — if a field is ever added/removed/re-required there,
this doc updates on its own, the same anti-drift guarantee.
"""
from . import canonical_status
from .serializers import AffiliateLeadSubmitSerializer


def _field_rows():
    rows = []
    for name, field in AffiliateLeadSubmitSerializer().fields.items():
        max_length = getattr(field, 'max_length', None)
        type_name = field.__class__.__name__.replace('Field', '').lower() or 'string'
        rows.append({
            'name': name,
            'required': bool(field.required),
            'type': type_name,
            'max_length': max_length,
            'help_text': field.help_text or '',
        })
    return rows


def build_doc_context(request, affiliate_user):
    """Everything one affiliate's personalized doc needs. `request` supplies
    the live base URL (no hardcoded domain — this works correctly in every
    environment, dev/staging/prod alike) and brand-scoping for their
    available offers (affiliate_ui._eligible_offers, reused, not
    reimplemented)."""
    from affiliate_ui.views.general_views import _eligible_offers
    from public_api.models import APIKey

    from .models import AffiliatePostbackConfig

    base_url = request.build_absolute_uri('/').rstrip('/')

    offers = _eligible_offers(request).order_by('title')
    keys = APIKey.objects.filter(user=affiliate_user, is_active=True).order_by('-created_at')
    postback_configs = AffiliatePostbackConfig.objects.filter(affiliate=affiliate_user, is_active=True)

    return {
        'base_url': base_url,
        'endpoints': [
            {'method': 'POST', 'path': '/api/leads/submit', 'purpose': 'Submit one lead.'},
            {'method': 'POST', 'path': '/api/leads/submit/batch', 'purpose': 'Submit up to 200 leads; partial success.'},
            {'method': 'GET', 'path': '/api/leads', 'purpose': "Pull your leads — filter by status, source_id, ids, updated_since."},
            {'method': 'GET', 'path': '/api/leads/<id>', 'purpose': 'One lead, including its full status timeline.'},
            {'method': 'GET', 'path': '/api/leads/statuses', 'purpose': 'The canonical status list below, as JSON.'},
        ],
        'fields': _field_rows(),
        'statuses': [{'value': value, 'label': label} for value, label in canonical_status.CHOICES],
        'offers': [{'id': o.pk, 'title': o.title} for o in offers],
        'keys': [
            {'id': k.pk, 'name': k.name, 'client_id': str(k.client_id),
             'requests_per_hour': k.requests_per_hour, 'created_at': k.created_at}
            for k in keys
        ],
        'postback_configs': [
            {'id': c.pk, 'url': c.url, 'subscribed_statuses': c.subscribed_statuses or ['(all statuses)']}
            for c in postback_configs
        ],
        'postback_macros': ['lead_id', 'source_id', 'status', 'status_time', 'offer_id', 'payout'],
        'openapi_schema_url': f'{base_url}/api/schema/',
        'openapi_swagger_url': f'{base_url}/api/schema/swagger-ui/',
    }
