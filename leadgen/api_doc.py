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
from .serializers import ATTRIBUTION_FIELDS, SUB_FIELDS, AffiliateLeadSubmitSerializer

# Example VALUES for the attribution fields in the curl samples below. The
# field NAMES are never listed here — they come from the serializer's own
# ATTRIBUTION_FIELDS/SUB_FIELDS, so a field renamed or dropped there changes
# the example instead of leaving the doc advertising something the API would
# now ignore. A name with no entry here simply doesn't appear in the sample.
EXAMPLE_ATTRIBUTION = {
    'funnel': 'crypto-quiz-v2',
    'campaign': 'summer-crypto',
    'medium': 'paid-social',
    'term': 'bitcoin-broker',
    'ad': 'video-ad-3',
    'sub1': 'your-own-value',
}

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
        'A postback URL is YOUR endpoint, on your own infrastructure — Nexora calls it. There '
        'is no Nexora URL to point at: you tell us where to push, and we push each status '
        'change to you as it happens. Macros in your URL are resolved fresh on every delivery.',
        'Register one either way, whichever suits you: POST /api/postbacks with your API key '
        '(no portal login needed — the endpoint is listed above), or on the Postbacks page of '
        'your dashboard. The signing secret is returned exactly once, when the postback is '
        'created; store it then, because it cannot be retrieved afterwards.',
        'You do not have to use postbacks at all. Polling GET /api/leads?updated_since=... '
        'returns the identical canonical status, so an integration that prefers to pull on its '
        'own schedule can skip this section entirely.',
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
    'attribution': [
        'Beyond the contact details, a lead carries where it came from: funnel, campaign, medium, '
        'term and ad, plus your own sub1..sub5 slots and the consumer\'s language. All are '
        'optional, and all are listed in the field table above.',
        'Send them. Where an offer\'s integration forwards a field, the buyer surfaces that value in '
        'their own reporting and optimises on it — a buyer that cannot tell your funnels apart '
        'cannot tell which of them is working, and that judgement is what decides whether they '
        'keep buying your traffic. One constant value across all your traffic is the same as '
        'sending nothing. Which fields a given offer forwards varies by integration; everything '
        'you send is stored and reportable here regardless.',
        'funnel/campaign/medium/term/ad are the named, validated fields — prefer them over sub '
        'slots wherever one fits, because only the named fields are reportable. sub1..sub5 are '
        'opaque passthrough: Nexora stores and returns them untouched and never interprets them.',
        'For a buyer field none of these names covers, send extra as an object of your own '
        'key/value pairs. Agree the key names with your account manager first: whether any of '
        'them reaches a buyer depends on that buyer being configured for the key, and an '
        'unrecognised key is stored and echoed back but goes no further.',
        'Any top-level field this API does not know is ignored rather than rejected, and its name '
        'is listed back to you as ignored_fields on the submit response. If you see a field there, '
        'it never left your own system — check it against the table above.',
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
    brand = _affiliate_brand(affiliate_user)
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
            'required_fields': _offer_required_fields(affiliate_user, offer, brand),
        })
    return rows


def _offer_required_fields(affiliate_user, offer, brand):
    """Inbound-API fields this offer needs ON TOP of the always-required ones,
    because the buyer it routes to refuses a lead without them — Hypernet
    boxes reject `geo`-less leads outright, and our own `country` is optional.

    DERIVED, never hand-maintained: it asks leadgen.requirements the same
    question intake asks, so the doc cannot promise an offer will accept
    something the endpoint then rejects. The probe lead is deliberately EMPTY
    apart from its routing keys — that models the worst-case submission, which
    is precisely the one this column exists to warn about.

    Costs one routing query per offer. Fine at the handful of offers a brand
    has; revisit with a per-brand rule prefetch if that ever stops being true.
    """
    from .models import Lead
    from .requirements import missing_buyer_requirements

    probe = Lead(
        brand=brand,
        intake_channel=Lead.CHANNEL_AFFILIATE_API,
        affiliate=affiliate_user,
        offer=offer,
    )
    return missing_buyer_requirements(probe)


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
        {'status': 400, 'when': 'A field this offer\'s buyer requires is missing — see the '
                                'Required column under "Offers you can send to".',
         'body': '{"country": ["This field is required for offer 12 — the buyer it routes to '
                 'rejects leads without it."]}'},
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


def _examples(base_url, offer_rows, *, offer_id_placeholder=None):
    """Copy-paste curl for single and batch submit, using a real approved
    offer_id where the affiliate has one.

    `offer_id_placeholder` is for the PUBLIC doc, which has no affiliate and
    therefore no offer list: it substitutes a literal like <YOUR_OFFER_ID> so
    the sample stays copy-pasteable-with-one-edit rather than quietly shipping
    an invented numeric id that would 400 on first use.

    The key stays a placeholder on purpose. This doc is downloadable as a PDF
    and text file the affiliate forwards to a traffic source, so embedding a
    live secret would put it in mailboxes, ticket systems and shared drives —
    the same reason the API takes the key in a header and never the query
    string. Secrets are shown once, in the UI, at creation.
    """
    offer_id = offer_id_placeholder or (offer_rows[0]['id'] if offer_rows else 123)
    key_placeholder = 'YOUR_API_KEY_HERE'
    single_body = {
        'first_name': 'Jane', 'last_name': 'Doe',
        'email': 'jane@example.com', 'phone': '+15551234567',
        'offer_id': offer_id, 'source_id': 'your-own-tracking-id',
        'country': 'GB', 'language': 'EN',
    }
    # The attribution block is shown filled in rather than omitted as
    # "optional": a buyer's reporting is keyed on it, and an affiliate copying
    # this curl is exactly the affiliate who would otherwise never send it.
    # Names from the serializer, values from EXAMPLE_ATTRIBUTION.
    for name in ATTRIBUTION_FIELDS + SUB_FIELDS:
        if name in EXAMPLE_ATTRIBUTION:
            single_body[name] = EXAMPLE_ATTRIBUTION[name]

    # Trimmed in the batch sample — the point there is the envelope, and two
    # fully-populated bodies bury it.
    batch_item = {k: v for k, v in single_body.items() if k not in EXAMPLE_ATTRIBUTION}
    batch_body = {'leads': [batch_item, dict(batch_item, email='john@example.com',
                                             first_name='John', source_id='your-second-id')]}

    def _curl(path, body):
        rendered = json.dumps(body, indent=2)
        if offer_id_placeholder:
            # json.dumps quotes it; the slot should read as a number, not a
            # string, or a copy-paste leaves offer_id as "<YOUR_OFFER_ID>".
            rendered = rendered.replace(f'"{offer_id_placeholder}"', offer_id_placeholder)
        return (
            f'curl -X POST {base_url}{path} \\\n'
            f'  -H "Authorization: ApiKey {key_placeholder}" \\\n'
            f'  -H "Content-Type: application/json" \\\n'
            f"  -d '{rendered}'"
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


def doc_base_url(request, brand):
    """`scheme://host` for a doc belonging to `brand`.

    The brand's OWN domain wins over the request's, falling back to the request
    only when the brand has no domain configured. That asymmetry is the whole
    point: BrandMiddleware resolves request.brand from the Host header and falls
    back to the default brand, so a doc built from the request could hand one
    tenant's affiliate another tenant's hostname — and this string is baked into
    every curl sample in a document people forward. Same rule as
    admin_views/registration_views; kept here so there is one copy to change.
    """
    host = (brand.primary_domain if brand else None) or request.get_host()
    scheme = 'https' if request.is_secure() else 'http'
    return f'{scheme}://{host}'.rstrip('/')


OFFER_ID_PLACEHOLDER = '<YOUR_OFFER_ID>' 


def _brand_conditional_required_fields(brand):
    """Inbound-API fields SOME of this brand's offers require beyond the always-
    required ones — the union across every buyer the brand can actually route to.

    The per-offer answer (see _offer_required_fields) needs an affiliate and an
    offer, and the public doc has neither. A union still tells an integrator the
    one thing that matters before they write any code — "this network will
    reject a lead with no country" — without naming a single offer.

    Deliberately NOT tenant-revealing: it returns field names like `country`,
    never buyers, offers or rules.
    """
    from .connectors import get_connector
    from .models import RoutingRule
    from .requirements import API_FIELD_NAMES

    if brand is None:
        return []
    buyers = {
        rule.buyer
        for rule in RoutingRule.objects
        .filter(brand=brand, is_active=True, buyer__is_active=True, buyer__brand=brand)
        .select_related('buyer__box_type')
    }
    names = set()
    for buyer in buyers:
        for attr in getattr(get_connector(buyer), 'REQUIRED_LEAD_FIELDS', ()):
            names.add(API_FIELD_NAMES.get(attr, attr))
    return sorted(names)


def build_public_doc_context(request, brand):
    """The doc with every tenant-specific part removed — for a page served with
    NO LOGIN, so it can be handed to a prospect, embedded in a proposal, or
    forwarded to a traffic source's own developers.

    Same dict shape as build_doc_context, from the same derived sources, so all
    three renderers and the shared template partial work unchanged. Exactly four
    things are emptied, and each is emptied because publishing it would be a
    real disclosure, not because it is merely irrelevant:

      * `offers`   — the brand's offer inventory. Competitors scrape this, and
                     keeping one tenant's offers away from another is the whole
                     point of the brand-only scoping ruling (2026-08-04);
                     publishing the list to the open internet is the same
                     disclosure with a wider audience.
      * `keys`     — API key client_ids. Not secrets, but identifiers of real
                     credentials, and there is no reason for them to be public.
      * `postback_configs` — the AFFILIATE's own endpoint URLs. Someone else's
                     infrastructure; ours to protect, not to publish.
      * `affiliate_name` — there is no affiliate here.

    The template partial already guards `keys` and `postback_configs` on
    truthiness, so emptying them removes those sections with no markup changes.

    Everything else — endpoints, all field rows, the status vocabulary, error
    bodies, postback macros, rate-limit rules, the narrative — is the CONTRACT.
    It is what an integrator needs and it discloses nothing: it is already
    enforced against anyone holding a key.
    """
    base_url = doc_base_url(request, brand)

    return {
        'public': True,
        'brand_name': brand.name if brand else '',
        'base_url': base_url,
        'affiliate_name': '',
        'auth_header': 'Authorization: ApiKey <your secret>',
        'endpoints': _endpoint_rows(),
        'pull_filters': _pull_filter_rows(),
        'fields': _field_rows(),
        'statuses': [{'value': value, 'label': label} for value, label in canonical_status.CHOICES],
        'offers': [],
        'conditional_required_fields': _brand_conditional_required_fields(brand),
        'keys': [],
        'postback_configs': [],
        'postback_macros': ['lead_id', 'source_id', 'status', 'status_time', 'offer_id', 'payout'],
        'errors': _error_rows(),
        'examples': _examples(base_url, [], offer_id_placeholder=OFFER_ID_PLACEHOLDER),
        'narrative': NARRATIVE,
        'openapi_schema_url': f'{base_url}/api/schema/',
        'openapi_swagger_url': f'{base_url}/api/schema/swagger-ui/',
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
    base_url = doc_base_url(request, brand)

    offers = _offer_rows(affiliate_user)
    keys = APIKey.objects.filter(user=affiliate_user, is_active=True).order_by('-created_at')
    postback_configs = AffiliatePostbackConfig.objects.filter(affiliate=affiliate_user, is_active=True)

    return {
        'public': False,
        'brand_name': brand.name if brand else '',
        'conditional_required_fields': [],
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
