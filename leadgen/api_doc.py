"""The single source of truth for an affiliate's personalized API
integration doc — Affiliate Inbound API spec §6. build_doc_context() is the
ONLY place that assembles this data; every render format (live HTML page,
PDF export, plain-text export) consumes the SAME dict, so they can never
drift from each other or from the real contract. Per spec §6.3: "rendered
from the SAME source of truth as the API itself... NEVER maintain the doc
as a separate static file."

Nothing here is hand-maintained prose about the API's shape:
  * endpoints come from this app's URL conf (any view carrying `doc_purpose`),
    so a newly routed endpoint documents itself and a documented path always
    really exists;
  * field rows are introspected off AffiliateLeadSubmitSerializer, so a field
    added/removed/re-required there updates the doc on its own;
  * statuses come from canonical_status.CHOICES;
  * error rows quote the actual messages the views and auth class return;
  * per-offer testing/live phase comes from AffiliateOfferLink.

The narrative paragraphs in NARRATIVE are the one thing that is genuinely
written text — they explain workflow, not contract. They live here rather
than in any template so that all three formats share one copy; before this,
the testing→live explainer existed twice (text view and HTML template) and
had already begun to diverge.
"""
import json

from . import canonical_status
from .serializers import AffiliateLeadSubmitSerializer

# Written explanation shared by every format. Plain strings, no markup, so
# HTML/PDF/text can each present them in their own idiom.
NARRATIVE = {
    'auth': [
        'Send your key in the Authorization header, never in the query string — a URL lands in '
        'server logs, proxies and browser history, and a leaked key can submit leads as you.',
        'Secrets are shown once, at creation or regeneration. If you lose one, regenerate it; '
        'anything still using the old secret stops working immediately.',
    ],
    'testing_live': [
        'Every offer you send to starts in TESTING: a Nexora operator sets your leads\' statuses '
        'by hand (walking a test lead through new → test → test_ftd) so you can confirm your own '
        'system receives and records them correctly.',
        'Once that is confirmed, Nexora flips that offer to LIVE. From then on the buyer\'s own '
        'reported status flows to you verbatim as the canonical value, by postback and via the '
        'pull API alike.',
        'The phase is per offer, not per account — you can be LIVE on one offer while still '
        'TESTING a new one. Your current phase for each offer is listed above.',
    ],
    'postbacks': [
        'Register a postback URL and Nexora pushes each status change to you as it happens. '
        'Macros in your URL are resolved fresh on every delivery.',
        'Every delivery is signed: X-Nexora-Signature: sha256=<hmac>, computed over the raw JSON '
        'body with your postback secret. Verify it before trusting the payload.',
        'Each payload carries a per-lead status_seq. Ignore any delivery whose seq is lower than '
        'one you have already recorded for that lead_id, so a late out-of-order retry can never '
        'regress a status you already hold.',
        'Failed deliveries are retried on a 60s / 300s / 1800s backoff. Your delivery log on the '
        'API & Docs page shows every attempt, response code and retry state.',
    ],
    'pull': [
        'Polling is the safety net for push. Ask for everything that changed since your last '
        'successful check with updated_since, and reconcile.',
        'Use it whenever a postback delivery to you fails, or as a periodic sweep — the canonical '
        'status is identical either way.',
        'updated_since compares against updated_at, which moves whenever anything about the lead '
        'changes — a status change, a deposit, a delivery outcome. It is not the creation time, so '
        'a lead you already pulled will come back again once it converts. Page through with the '
        '"next" URL, and keep the newest updated_at you saw as the cursor for your next poll.',
        'Responses are a standard page envelope: count, next, previous, results.',
    ],
    'conversions': [
        'A conversion is a canonical status, not a separate endpoint: pull it with '
        'GET /api/leads?status=ftd. There is no /conversions resource.',
        'ftd is the First Time Deposit. qualified_ftd is an FTD that additionally met the '
        'campaign\'s qualification bar and is the billable one; redeposit is a further deposit '
        'after the first; high_value flags a VIP depositor.',
        'test_ftd is the TESTING-phase rehearsal of an FTD — it exists so you can prove your '
        'integration records a deposit correctly before the offer goes live. Never count it as '
        'revenue.',
        'chargeback reverses a previous deposit, so treat it as a negative event against a lead '
        'you have already counted rather than as a new one.',
        'Each lead also carries a deposit boolean and the buyer\'s own raw buyer_status string. '
        'Prefer canonical_status: it is the value Nexora guarantees and the one postbacks send. '
        'The other two are passed through for reconciliation and debugging.',
    ],
    'rate_limits': [
        'Limits are per API key and shown with your keys above. Exceeding one returns 429 — back '
        'off and retry rather than tightening your loop.',
    ],
}


def _display_path(route):
    """'api/leads/<int:pk>' -> '/api/leads/<id>' — the URL conf's own route,
    with Django's converter syntax reduced to something an integrator reads."""
    out = []
    for part in route.split('/'):
        if part.startswith('<') and part.endswith('>'):
            name = part[1:-1].split(':')[-1]
            out.append('<id>' if name == 'pk' else f'<{name}>')
        else:
            out.append(part)
    return '/' + '/'.join(out).strip('/')


def _endpoint_rows():
    """Every documented endpoint, read off this app's URL conf rather than
    hand-listed. A view opts in by defining `doc_purpose`; the method comes
    from the handlers the class actually implements, so the doc can't claim
    a verb the endpoint doesn't answer."""
    from . import urls as leadgen_urls

    rows = []
    for pattern in leadgen_urls.urlpatterns:
        view_class = getattr(pattern.callback, 'cls', None)
        purpose = getattr(view_class, 'doc_purpose', '')
        if not purpose:
            continue
        methods = [
            verb.upper() for verb in ('get', 'post', 'put', 'patch', 'delete')
            if callable(getattr(view_class, verb, None))
        ]
        rows.append({
            'method': ', '.join(methods),
            'path': _display_path(str(pattern.pattern)),
            'purpose': purpose,
        })
    return rows


def _pull_filter_rows():
    """The query parameters GET /api/leads accepts, read off the view's own
    `doc_filters` rather than retyped here — same anti-drift rule as
    doc_purpose. Returns [] if the view ever stops declaring them, which is
    visible in the doc rather than silently wrong."""
    from .api_views import LeadListView

    return list(getattr(LeadListView, 'doc_filters', []))


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


def _affiliate_brand(affiliate_user):
    """The brand the affiliate BELONGS to — not the brand of whatever domain
    they happened to reach the portal through.

    This distinction is the whole point of sourcing the doc from the affiliate.
    BrandMiddleware resolves request.brand from the Host header and falls back
    to the default brand when it doesn't match, and login is not brand-gated,
    so a Thika affiliate who reaches the Nexora domain has request.brand =
    Nexora. A doc built from that would hand them Nexora's host AND Nexora's
    offer_ids — another tenant's data, embedded in a document they forward to
    their traffic source.
    """
    return getattr(getattr(affiliate_user, 'profile', None), 'brand', None)


def _offer_rows(affiliate_user):
    """The offers this affiliate may send to, each with its current
    testing/live phase. Delegates to offers_for_affiliate — the one scoping
    rule every affiliate surface shares — so the doc lists exactly what the
    offers page shows and exactly what the inbound API will accept, and never
    an unbranded/shared offer. An offer with no AffiliateOfferLink row yet
    reads as TESTING and not-yet-started, which is exactly what would happen
    on first submission — spec §2.1: a new integration is never born live."""
    from affiliate_ui.views.general_views import offers_for_affiliate

    from .models import AffiliateOfferLink

    phases = dict(
        AffiliateOfferLink.objects
        .filter(affiliate=affiliate_user)
        .values_list('offer_id', 'phase')
    )
    labels = dict(AffiliateOfferLink.PHASE_CHOICES)
    rows = []
    for offer in offers_for_affiliate(affiliate_user).order_by('title'):
        phase = phases.get(offer.pk, AffiliateOfferLink.PHASE_TESTING)
        rows.append({
            'id': offer.pk,
            'title': offer.title,
            'phase': phase,
            'phase_label': labels[phase],
            'is_live': phase == AffiliateOfferLink.PHASE_LIVE,
            'started': offer.pk in phases,
        })
    return rows


def _error_rows():
    """The responses an integrator must actually handle, quoting the real
    messages from leadgen.api_views and public_api.authentication so the doc
    matches what the endpoint returns byte for byte."""
    from .api_views import MAX_BATCH_SIZE, IsAffiliate

    return [
        {'status': 400, 'when': 'A required field is missing, or a value fails validation.',
         'body': '{"email": ["This field is required."]}'},
        {'status': 400, 'when': 'offer_id is not an offer you are approved to send to.',
         'body': '{"detail": "offer_id does not resolve to an offer you can send to."}'},
        {'status': 400, 'when': 'A batch call with no "leads" list, or an empty one.',
         'body': '{"detail": "\\"leads\\" must be a non-empty list."}'},
        {'status': 400, 'when': f'A batch of more than {MAX_BATCH_SIZE} leads.',
         'body': f'{{"detail": "Maximum {MAX_BATCH_SIZE} leads per batch."}}'},
        {'status': 400, 'when': 'A batch in which every lead failed (partial success returns 201).',
         'body': '{"addedLeads": [], "failedToAddLeads": [{"input": {...}, "errors": {...}}]}'},
        {'status': 401, 'when': 'Missing, unknown, revoked or malformed API key.',
         'body': '{"detail": "Invalid or inactive API key."}'},
        {'status': 403, 'when': 'A valid key that does not belong to an affiliate account.',
         'body': f'{{"detail": "{IsAffiliate.message}"}}'},
        {'status': 404, 'when': 'A lead id that does not exist, or is not yours.',
         'body': '{"detail": "Not found."}'},
        {'status': 429, 'when': 'Your key exceeded its rate limit.',
         'body': '{"detail": "Request was throttled. Expected available in N seconds."}'},
    ]


def _examples(base_url, offer_rows):
    """Copy-paste curl for single and batch submit, using a real approved
    offer_id where the affiliate has one.

    The key stays a placeholder on purpose. This doc is downloadable as a PDF
    and text file the affiliate forwards to a traffic source, so embedding a
    live secret would put it in mailboxes, ticket systems and shared drives —
    the same reason the API takes the key in a header and never the query
    string. Secrets are shown once, in the UI, at creation.
    """
    offer_id = offer_rows[0]['id'] if offer_rows else 123
    key_placeholder = 'YOUR_API_KEY_HERE'
    single_body = {
        'first_name': 'Jane', 'last_name': 'Doe',
        'email': 'jane@example.com', 'phone': '+15551234567',
        'offer_id': offer_id, 'source_id': 'your-own-tracking-id',
    }
    batch_body = {'leads': [single_body, dict(single_body, email='john@example.com',
                                              first_name='John', source_id='your-second-id')]}

    def _curl(path, body):
        return (
            f'curl -X POST {base_url}{path} \\\n'
            f'  -H "Authorization: ApiKey {key_placeholder}" \\\n'
            f'  -H "Content-Type: application/json" \\\n'
            f"  -d '{json.dumps(body, indent=2)}'"
        )

    return {
        'offer_id_used': offer_id,
        'single_curl': _curl('/api/leads/submit', single_body),
        'batch_curl': _curl('/api/leads/submit/batch', batch_body),
        'pull_curl': (
            f'curl "{base_url}/api/leads?updated_since=2026-01-01T00:00:00Z" \\\n'
            f'  -H "Authorization: ApiKey {key_placeholder}"'
        ),
    }


def build_doc_context(request, affiliate_user):
    """Everything one affiliate's personalized doc needs.

    Host and offers both come from the affiliate's OWN brand, not from the
    request — mirroring the pattern in affiliate_ui.views.admin_views and
    registration_views. `request` still supplies the scheme and the host
    fallback, so there is no hardcoded domain and this stays correct in every
    environment; but a doc is a durable artifact the affiliate forwards to a
    traffic source, so it must describe *their* integration regardless of
    which domain they were looking at when they generated it.
    """
    from public_api.models import APIKey

    from .models import AffiliatePostbackConfig

    brand = _affiliate_brand(affiliate_user)
    host = (brand.primary_domain if brand else None) or request.get_host()
    scheme = 'https' if request.is_secure() else 'http'
    base_url = f'{scheme}://{host}'.rstrip('/')

    offers = _offer_rows(affiliate_user)
    keys = APIKey.objects.filter(user=affiliate_user, is_active=True).order_by('-created_at')
    postback_configs = AffiliatePostbackConfig.objects.filter(affiliate=affiliate_user, is_active=True)

    return {
        'base_url': base_url,
        'affiliate_name': affiliate_user.get_full_name() or affiliate_user.get_username(),
        'auth_header': 'Authorization: ApiKey <your secret>',
        'endpoints': _endpoint_rows(),
        'pull_filters': _pull_filter_rows(),
        'fields': _field_rows(),
        'statuses': [{'value': value, 'label': label} for value, label in canonical_status.CHOICES],
        'offers': offers,
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
        'errors': _error_rows(),
        'examples': _examples(base_url, offers),
        'narrative': NARRATIVE,
        'openapi_schema_url': f'{base_url}/api/schema/',
        'openapi_swagger_url': f'{base_url}/api/schema/swagger-ui/',
    }
