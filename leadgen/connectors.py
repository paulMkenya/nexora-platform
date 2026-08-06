"""Generic, config-driven connector for outbound lead delivery.

Phase 4 of the lead-distribution build (the Box Registry — see
leadgen/README.md): every platform-level setting this connector reads —
endpoint paths, auth scheme, rate-limit policy, the canonical field set —
now comes from the buyer's BoxType (leadgen.models.BoxType), not the
LeadBuyer row itself. A LeadBuyer is now the *instance*: which BoxType it
speaks, its own base_url + encrypted API key, and field-name overrides on
top of the BoxType's defaults (get_effective_field_mapping()). Handles the
common REST + query-string-or-header API key + JSON single/batch leads
shape used by most lead-buyer platforms — op-brandy.com, BoxType #1, is
exactly this shape. Onboarding a new brand on a KNOWN box is a LeadBuyer
row, no code. A genuinely different platform (a different auth scheme
entirely, XML, SOAP) gets its own BoxType.connector_class (a dotted
Python path, resolved via get_connector() below — declarative selection,
never eval'd code) pointing at a subclass overriding _request()/
build_payload()/parse_injection_result().

Security posture (deliberate, mirrors payouts/providers/nowpayments/base.py):
  * Every call is timeout-bounded so a hung buyer endpoint can never wedge a
    Celery worker.
  * The API key is never logged — request/response audit trail
    (LeadInjection.request_payload/response_payload) is built from the
    MAPPED LEAD FIELDS only, never from the raw HTTP headers/query string.
  * Error messages carry only the status code + a sanitized response snippet.
  * Rate-limited client-side via TokenBucket BEFORE every call, so we act as
    a good citizen of the buyer's own documented policy instead of reacting
    to their 429s after the fact.
"""
import logging
import re
import secrets
from urllib.parse import urljoin

import requests

from nexora.crypto import decrypt_secret, encrypt_secret

from .ratelimit import TokenBucket

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 15

# our field name -> Lead model attribute. Single source of truth for both
# build_payload() below and the console's field-mapping override editor
# (admin_views.py/buyer_form) — the only keys a field_mapping override can
# meaningfully affect.
MAPPABLE_LEAD_FIELDS = {
    'firstname': 'first_name',
    'lastname': 'last_name',
    'email': 'email',
    'phone': 'phone',
    'vertical': 'vertical',
    'source_id': 'source_id',
}


class LeadBuyerError(Exception):
    """A buyer API call failed. The base class means RETRYABLE.

    Carries the HTTP ``status_code`` (``None`` for transport/connection
    errors) and a ``message`` that is already sanitized.

    THE FULL CLASSIFICATION — every failure mode _request() can produce maps
    to exactly one of three outcomes. This table is the contract; nothing
    else in the codebase gets to reinterpret it:

    ==========================  ==================  =========================
    Condition                   Raises              Caller must
    ==========================  ==================  =========================
    4xx, except 429             RejectedError       cascade now, 0 retries
    429 (rate limited)          LeadBuyerError      retry with backoff
    ConnectTimeout / refused    LeadBuyerError      retry with backoff
    / DNS failure
    502 / 503 / 504             LeadBuyerError      retry with backoff
    other 5xx (not 500)         LeadBuyerError      retry with backoff
    ReadTimeout                 AmbiguousError      quarantine
    500                         AmbiguousError      quarantine
    2xx, unparseable body       AmbiguousError      quarantine
    ==========================  ==================  =========================

    The reasoning behind the two non-obvious rows:

    * **429 is not a rejection.** It is "slow down", not "we looked and said
      no". Cascading it hands the lead to a competitor when the intended
      buyer would have taken it seconds later.
    * **502/503/504 are not ambiguous.** A gateway or unavailable response
      means the request never reached the buyer's application, so nothing
      was created and retrying is safe. 500 is different: their app took the
      request and then fell over, possibly after creating the lead.

    BOTH subclasses must be caught BEFORE this base class, or their guards
    are silently inert — see each subclass's own docstring.
    """

    def __init__(self, message: str, *, status_code: int | None = None):
        self.status_code = status_code
        self.message = message
        super().__init__(message if status_code is None else f'[{status_code}] {message}')


class LeadBuyerRejectedError(LeadBuyerError):
    """The buyer evaluated this lead and said no. Terminal for THIS buyer.

    Cascade to the next buyer immediately; do NOT retry. A 400/403/422 means
    they looked at the payload and refused it — the identical payload will be
    refused identically in 60 seconds, so the retry budget is pure latency
    added to the lead's time-to-contact, and time-to-contact is the thing
    that decides whether a lead converts.

    Excludes 429, which is rate-limiting, not rejection — see LeadBuyerError's
    table.

    Subclasses LeadBuyerError so existing ``except LeadBuyerError`` handlers
    still catch it, which means a handler testing the BASE first makes this
    inert. Order: LeadBuyerAmbiguousError, then LeadBuyerRejectedError, then
    LeadBuyerError.
    """


class LeadBuyerAmbiguousError(LeadBuyerError):
    """The buyer MAY have accepted this lead. Never retry, never cascade.

    THE CONTRACT — any handler catching LeadBuyerError that intends to retry
    or cascade MUST check for LeadBuyerAmbiguousError FIRST and quarantine;
    only a non-ambiguous LeadBuyerError may be retried or advanced to the
    next buyer. This subclasses LeadBuyerError deliberately so existing
    ``except LeadBuyerError`` blocks keep catching it rather than letting it
    escape — which means an `except` chain that tests the BASE first makes
    this guard silently inert. Order matters:

        try:
            ...
        except LeadBuyerAmbiguousError:   # MUST come first
            quarantine(...)               # no retry, no cascade
        except LeadBuyerRejectedError:    # then this
            cascade_now(...)              # no retry
        except LeadBuyerError:            # base LAST
            retry_with_backoff(...)

    Raised ONLY when the request demonstrably reached the buyer AND the
    outcome is indeterminate — we cannot tell whether they took the lead.
    Selling it again would be a double-sell; retrying it against the same
    buyer would risk a duplicate. Neither is recoverable, so the lead stops
    and a human looks at it.

    NEVER raised when the buyer provably did not receive the request (DNS
    failure, connection refused, connect timeout) — those stay a plain
    LeadBuyerError and remain safely retryable.
    """


# See LeadBuyerError's table. 500 only: their application received the
# request and then failed, possibly after creating the lead. 502/503/504 mean
# it never got there, so they stay retryable.
AMBIGUOUS_STATUS_CODES = frozenset({500})

# Rate limiting is not a rejection — it is "slow down". Cascading it would
# hand the lead to a competitor the intended buyer would have taken.
RATE_LIMITED_STATUS_CODE = 429


class LeadBuyerAmbiguousError(LeadBuyerError):
    """The buyer MAY have accepted this lead. Never retry, never cascade.

    THE CONTRACT — any handler catching LeadBuyerError that intends to retry
    or cascade MUST check for LeadBuyerAmbiguousError FIRST and quarantine;
    only a non-ambiguous LeadBuyerError may be retried or advanced to the
    next buyer. This subclasses LeadBuyerError deliberately so existing
    ``except LeadBuyerError`` blocks keep catching it rather than letting it
    escape — which means an `except` chain that tests the BASE first makes
    this guard silently inert. Order matters:

        try:
            ...
        except LeadBuyerAmbiguousError:   # MUST come first
            quarantine(...)               # no retry, no cascade
        except LeadBuyerError:
            retry_or_cascade(...)

    Raised ONLY when the request demonstrably reached the buyer AND the
    outcome is indeterminate — we cannot tell whether they took the lead.
    Selling it again would be a double-sell; retrying it against the same
    buyer would risk a duplicate. Neither is recoverable, so the lead stops
    and a human looks at it.

    NEVER raised when the buyer provably did not receive the request (DNS
    failure, connection refused, connect timeout) — those stay a plain
    LeadBuyerError and remain safely retryable.
    """


# HTTP statuses that mean "the buyer's application received and processed
# this request, and then something went wrong inside it" — the buyer may
# already have created the lead. 502/503/504 are deliberately NOT here: a
# gateway/unavailable response means the request never reached the
# application, so it is safely retryable.
AMBIGUOUS_STATUS_CODES = frozenset({500})


# What replaces a value that isn't on an audit allowlist. The KEY is kept so
# the recorded shape still shows what the buyer sent back (and so a diff
# against a later response is still meaningful) — only the value is dropped.
REDACTED = '[redacted]'


def _sanitize_for_audit(value, allowlist: frozenset):
    """Recursively default-deny ``value`` against ``allowlist``.

    One flat set of key NAMES, applied at every depth: a key not in the set
    has its value replaced by REDACTED regardless of where it appears, so a
    credential can't hide inside a nested object or a list of objects.
    Lists are walked, scalars pass through.

    Default-deny rather than a blocklist on purpose: the fields worth
    catching are the ones nobody anticipated. A blocklist only ever catches
    what someone already thought of, which is exactly the field that won't
    be there when a buyer changes their API.
    """
    if isinstance(value, dict):
        return {
            key: (_sanitize_for_audit(item, allowlist) if key in allowlist else REDACTED)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_sanitize_for_audit(item, allowlist) for item in value]
    return value


def _sanitize_body(resp) -> str:
    try:
        text = resp.text or ''
    except Exception:  # noqa: BLE001 — never let logging/error-building raise
        return '<unreadable response body>'
    text = text.replace('\n', ' ').strip()
    return text[:300] if text else '<empty response body>'


def get_connector(buyer, *, timeout: int | None = None):
    """Instantiate the right connector class for `buyer`, per its
    box_type.connector_class (a dotted Python path — declarative
    selection via Django's own import_string, the same safe mechanism
    behind AUTHENTICATION_BACKENDS/STORAGES/etc. — not eval'd code). Every
    caller that used to do LeadBuyerConnector(buyer) directly should use
    this instead, so a buyer on a non-default BoxType actually gets its
    own connector class."""
    from django.utils.module_loading import import_string

    connector_cls = import_string(buyer.box_type.connector_class)
    return connector_cls(buyer, timeout=timeout)


class LeadBuyerConnector:
    """Connector for one configured LeadBuyer, fully config-driven — reads
    platform-level behavior from buyer.box_type, instance-level identity
    (base_url, API key) from buyer itself."""

    # Whether this connector implements fetch_lead_statuses()/
    # parse_status_sync_results() for real. leadgen.tasks.
    # sync_buyer_statuses_for_buyer checks this and skips the buyer entirely
    # when it's False, so a connector that deliberately does not support
    # status sync (see HypernetConnector) fails fast at the scheduler rather
    # than raising NotImplementedError on every Celery Beat tick. A class
    # attribute rather than a BoxType column on purpose: this is a property
    # of the CODE, not of an operator-editable configuration row — nobody
    # should be able to tick a checkbox that makes a method exist.
    supports_status_sync = True

    # Default-deny allowlist for what may be recorded on
    # LeadInjection.response_payload — see sanitize_response_for_audit().
    # These are op-brandy's own envelope + result keys. Everything else a
    # buyer returns is redacted, at any nesting depth.
    #
    # Note what is deliberately NOT here: the lead's own echoed details
    # (email/firstname/lastname/phoneNumber/...). We already store all of
    # that on the Lead row; re-recording the buyer's copy in a second place
    # buys nothing and widens the blast radius of anything that reads
    # response_payload — which today includes an affiliate-facing template
    # (affiliate_ui/templates/affiliate_ui/leads.html).
    AUDIT_RESPONSE_ALLOWLIST = frozenset({
        'addedLeads', 'failedToAddLeads', 'id', 'failureReason', 'failureMessages',
    })

    # Per-box HTTP timeout. A class attribute rather than a BoxType column
    # because it is a property of the platform's own latency, discovered by
    # integrating against it — not something an operator should be tuning
    # from a form. A subclass raises it for a box that is genuinely slow.
    #
    # This matters more than an ordinary tuning knob: a timeout that fires
    # while the buyer is still processing produces an AMBIGUOUS outcome (see
    # LeadBuyerAmbiguousError), which quarantines a lead that may well have
    # been accepted. Too low a value therefore does not merely retry — it
    # strands good leads and creates manual reconciliation work.
    default_timeout = DEFAULT_TIMEOUT

    def __init__(self, buyer, *, timeout: int | None = None):
        self.buyer = buyer
        self.box_type = buyer.box_type
        self.timeout = timeout if timeout is not None else self.default_timeout
        self._bucket = TokenBucket.for_buyer(buyer)

    # --- payload mapping -----------------------------------------------------

    def _map_field(self, our_name: str) -> str:
        return self.buyer.get_effective_field_mapping().get(our_name, our_name)

    def build_payload(self, lead) -> dict:
        """Map a leadgen.Lead onto the buyer's own field names. ``deposit``
        is deliberately NOT sent here — a lead has no deposit at submission
        time; deposit status flows the other way, via
        leadgen.tasks.sync_buyer_statuses (see fetch_lead_statuses() below)."""
        values = {our_name: getattr(lead, attr) for our_name, attr in MAPPABLE_LEAD_FIELDS.items()}
        values['source_id'] = lead.source_id or str(lead.pk)
        payload = {}
        for our_name, value in values.items():
            if value in (None, ''):
                continue
            payload[self._map_field(our_name)] = value
        return payload

    # --- transport -------------------------------------------------------------

    def _build_url(self, path: str) -> str:
        return urljoin(self.buyer.base_url.rstrip('/') + '/', path.lstrip('/'))

    def _request(self, method: str, path: str, *, json: dict | None = None, params: dict | None = None):
        """Rate-limited, timeout-bounded, sanitized-on-error request. Blocks
        (via TokenBucket.acquire) if the client-side bucket is empty — only
        ever call this from a background task, never a request/response cycle."""
        url = self._build_url(path)
        headers = {'Content-Type': 'application/json'}
        params = dict(params or {})
        api_key = self.buyer.get_api_key()
        box_type = self.box_type

        if box_type.auth_type == box_type.AUTH_API_KEY_QUERY:
            params[box_type.auth_param_name] = api_key
        elif box_type.auth_type == box_type.AUTH_API_KEY_HEADER:
            headers[box_type.auth_param_name] = api_key
        elif box_type.auth_type == box_type.AUTH_BEARER:
            headers['Authorization'] = f'Bearer {api_key}'

        self._bucket.acquire()
        try:
            resp = requests.request(
                method, url, headers=headers, params=params, json=json, timeout=self.timeout)
        except requests.ReadTimeout as exc:
            # The request WAS sent and we never heard back. The buyer may
            # have processed it — the classic double-sell vector. Checked
            # before ConnectTimeout/ConnectionError below because
            # ConnectTimeout subclasses both ConnectionError and Timeout,
            # while ReadTimeout subclasses only Timeout.
            raise LeadBuyerAmbiguousError(
                f'{method} {path}: read timeout after {self.timeout}s — request was sent, '
                'outcome unknown.') from exc
        except requests.RequestException as exc:
            # DNS failure, connection refused, connect timeout: the buyer
            # never received it, so this stays safely retryable.
            raise LeadBuyerError(f'request to {path} failed: {exc.__class__.__name__}') from exc

        if not resp.ok:
            code = resp.status_code
            detail = f'{method} {path} -> {_sanitize_body(resp)}'
            # Order mirrors the table in LeadBuyerError's docstring, most
            # specific first. 500 is checked before the 4xx branch purely so
            # the sequence reads the same way callers must write their
            # `except` chain.
            if code in AMBIGUOUS_STATUS_CODES:
                raise LeadBuyerAmbiguousError(detail, status_code=code)
            if 400 <= code < 500 and code != RATE_LIMITED_STATUS_CODE:
                # They evaluated the payload and refused it. The identical
                # payload will be refused identically in 60 seconds, so the
                # retry budget is pure added latency on a lead's
                # time-to-contact. Cascade now instead.
                raise LeadBuyerRejectedError(detail, status_code=code)
            # 429 and every 5xx that is not 500: retryable.
            raise LeadBuyerError(detail, status_code=code)
        if not resp.content:
            return {}
        try:
            return resp.json()
        except ValueError as exc:
            # A 2xx we cannot parse: the buyer said "OK" in a shape we don't
            # understand. Whether the lead landed is exactly what we cannot
            # determine, so this must not be retried or cascaded.
            raise LeadBuyerAmbiguousError(
                f'{method} {path} returned a non-JSON body on a {resp.status_code}.',
                status_code=resp.status_code) from exc

    # --- public API --------------------------------------------------------------

    def inject_lead(self, lead) -> dict:
        """POST one lead. Returns the buyer's parsed response dict.
        Raises LeadBuyerError on transport/HTTP failure — the Celery task
        (tasks.py) translates that into a LeadInjection row."""
        payload = self.build_payload(lead)
        return self._request('POST', self.box_type.single_endpoint_path, json=payload)

    def inject_batch(self, leads) -> dict:
        """POST a batch. Returns the buyer's parsed response dict — the
        added/failed split is buyer-specific, callers inspect the raw
        response (see tasks.inject_batch_task)."""
        if not self.buyer.supports_batch:
            raise LeadBuyerError(f'{self.buyer.name} does not support batch injection')
        payload = {'leads': [self.build_payload(lead) for lead in leads]}
        return self._request('POST', self.box_type.batch_endpoint_path, json=payload)

    def fetch_leads(self, **filters) -> dict:
        return self._request('GET', self.box_type.fetch_endpoint_path, params=filters)

    # --- response parsing --------------------------------------------------------

    def parse_injection_result(self, response: dict) -> tuple[str, str, str]:
        """(external_id, status, failure_reason) from a single-lead inject
        response. Default assumes op-brandy's envelope — both its single and
        batch endpoints return {"addedLeads": [...], "failedToAddLeads": [...]}
        — which is common enough across this class of API to be the sane
        default; a buyer on a BoxType with a different envelope gets its own
        connector_class overriding this one method.
        """
        added = response.get('addedLeads') or []
        failed = response.get('failedToAddLeads') or []
        if added:
            item = added[0]
            return str(item.get('id') or ''), 'delivered', ''
        if failed:
            item = failed[0]
            reason = item.get('failureReason') or ''
            status = 'duplicate' if reason == 'duplicate' else 'failed'
            messages = item.get('failureMessages') or []
            detail = '; '.join(messages) if messages else reason
            return '', status, detail[:255]
        # Neither list present/populated — treat as an unexpected-but-2xx
        # response rather than silently calling it a success.
        return '', 'failed', 'Unexpected response shape (no addedLeads/failedToAddLeads)'

    def sanitize_response_for_audit(self, response):
        """What may be persisted to LeadInjection.response_payload.

        The raw buyer response is NOT safe to store verbatim: it can carry
        credentials (Hypernet's ``redirectUrl`` is an autologin bearer URL)
        and it is surfaced to affiliates by
        affiliate_ui/templates/affiliate_ui/leads.html. This filters it
        default-deny against AUDIT_RESPONSE_ALLOWLIST — a subclass narrows
        or widens that set for its own envelope, and anything the buyer
        adds later is redacted until someone deliberately allows it.

        Called by leadgen.tasks.inject_lead_task in place of assigning the
        raw response. A non-JSON-object response has nothing worth auditing
        and becomes {} (response_payload is a JSONField defaulting to dict).
        """
        if not isinstance(response, (dict, list)):
            return {}
        return _sanitize_for_audit(response, self.AUDIT_RESPONSE_ALLOWLIST)

    def fetch_lead_statuses(self, external_ids) -> dict:
        """GET leads by their buyer-assigned IDs (op-brandy's ``Ids`` filter
        on GET /leads — the SAME endpoint used by fetch_leads(), which
        returns deposit + status.name/updatedAtUtc for every lead regardless
        of deposit state, not just deposited ones). Used by
        leadgen.tasks.sync_buyer_statuses to pull whatever CRM/call-center
        progression the buyer tracks (New, Deposit, Did not pick call, Asked
        for followup, ...) — their own free-text status, not ours."""
        if not external_ids:
            return {'items': []}
        return self.fetch_leads(Ids=list(external_ids), PageSize=len(external_ids))

    def parse_status_sync_results(self, response: dict) -> list[dict]:
        """[{'external_id', 'buyer_status', 'deposit', 'updated_at',
        'country_iso2'}, ...] from a fetch_lead_statuses() response. Default
        assumes op-brandy's item shape (id / deposit / status.name /
        status.updatedAtUtc / countryIso2) — a buyer on a BoxType with a
        different GET /leads shape gets its own connector_class overriding
        this method. ``country_iso2`` is a free byproduct of this same call
        (the buyer derives it from the phone number on their side) — a
        zero-cost backfill for Lead.country_iso2 alongside IPSTACK-based
        geolocation at intake (see tasks.geolocate_lead)."""
        results = []
        for item in response.get('items') or []:
            status = item.get('status') or {}
            external_id = str(item.get('id') or '')
            if not external_id:
                continue
            results.append({
                'external_id': external_id,
                'buyer_status': status.get('name') or '',
                'deposit': bool(item.get('deposit')),
                'updated_at': status.get('updatedAtUtc') or '',
                'country_iso2': (item.get('countryIso2') or '')[:2],
            })
        return results


# --- Hypernet (HTN-AFF-SDK) ---------------------------------------------------

# Visual separators an operator or an affiliate's own form may leave in a
# phone number. Stripped before anything else is decided.
_PHONE_SEPARATORS = re.compile(r'[\s\-().]')


def _normalize_msisdn(raw) -> tuple[str, bool]:
    """(digits, is_ambiguous) — a phone number in the bare international
    form Hypernet documents ("phone (no leading +)").

    Two prefixes mean the same thing and are both removed: a leading ``+``
    and a leading ``00`` (the ITU international access code). Everything
    else is left alone.

    ``is_ambiguous`` is True when the result still starts with ``0``, i.e.
    the number arrived in NATIONAL format ("0712345678") with no country
    code. That cannot be resolved here — turning it into an international
    number needs a dialing plan for the lead's country, and guessing one
    would deliver a wrong number to a buyer who charges us per lead. The
    caller decides what to do; this function never invents a country code.

    Note what is deliberately NOT done: no attempt to strip a national
    trunk prefix after a country code, no length validation. Both need a
    real per-country dialing plan (libphonenumber), which is an intake
    concern — see leadgen.serializers._PHONE_RE, which today accepts any
    7-15 digits with an optional ``+``.
    """
    digits = _PHONE_SEPARATORS.sub('', str(raw or '').strip())
    if digits.startswith('+'):
        digits = digits[1:]
    elif digits.startswith('00'):
        digits = digits[2:]
    return digits, digits.startswith('0')


def _set_path(target: dict, dotted_key: str, value):
    """Assign ``value`` into ``target`` at a dotted path, creating the
    intervening dicts. ``_set_path(d, 'profile.firstName', 'Jane')`` gives
    ``{'profile': {'firstName': 'Jane'}}``; a key with no dot behaves exactly
    like ``target[key] = value``.

    This exists because LeadBuyer.field_mapping is FLAT — the base
    build_payload() writes ``payload[mapped_name] = value``, so a mapping can
    only ever name a top-level key. Hypernet wants the lead's own attributes
    nested under ``profile``, so HypernetConnector reinterprets a mapped name
    containing dots as a path. Only this connector does so; the base's
    behavior for every other buyer is unchanged.
    """
    parts = dotted_key.split('.')
    node = target
    for part in parts[:-1]:
        nxt = node.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            node[part] = nxt
        node = nxt
    node[parts[-1]] = value


class HypernetConnector(LeadBuyerConnector):
    """Connector for Hypernet-CRM-style boxes (HTN-AFF-SDK) — the second box
    onboarded after op-brandy, and the first that genuinely needed its own
    connector_class rather than just a LeadBuyer row.

    Four things about Hypernet the generic connector cannot express:

    1. **Response envelope.** Injection returns
       ``{"success": true, "redirectUrl": "...", "leadId": "..."}``, not
       op-brandy's ``{"addedLeads": [...], "failedToAddLeads": [...]}``. The
       base parse_injection_result() would fall through to its
       "Unexpected response shape" branch and log every successful delivery
       as a failure — see parse_injection_result() below.

    2. **Static per-buyer constants.** Every request body must carry this
       box's ``affc``/``bxc``/``vtc`` (and its funnel/language constants),
       which are properties of the BUYER, not of the lead — nothing
       build_payload() maps. They come from
       ``LeadBuyer.extra_payload_fields`` and are merged in below.

    3. **Nested profile.** The lead's own fields live under ``profile``.
       field_mapping is flat (it can only name a top-level key), so this
       connector reads dots in a mapped name as a path — see _set_path().

    4. **Fields outside MAPPABLE_LEAD_FIELDS.** Hypernet wants ``ip`` and
       ``geo``, which exist on Lead (``ip`` / ``country_iso2``) but are not
       in MAPPABLE_LEAD_FIELDS, and a ``profile.password``, which has no
       Lead field at all. Adding them to MAPPABLE_LEAD_FIELDS would change
       what we send to the live op-brandy box, so they are assembled here
       instead — see build_payload() / get_or_create_password().

    Status sync is deliberately NOT implemented: Hypernet's GET endpoint
    filters by date range, not by an ID list, so the base class's
    Ids-based fetch would silently return nothing useful. See
    fetch_lead_statuses().
    """

    # Measured against the live desperados box: a successful POST took 11.8s,
    # and an earlier attempt exceeded the 15s default outright. Their box is
    # simply slow to answer. At the default this intermittently produced a
    # read timeout -> AMBIGUOUS -> quarantine for leads that had NOT actually
    # been rejected, each needing a human to check their system by hand.
    # 60s leaves real headroom over the observed latency while still bounding
    # a hung endpoint well inside a Celery worker's tolerance.
    default_timeout = 60

    # Status sync is not implemented for this box — see fetch_lead_statuses().
    # This is what keeps leadgen.tasks.sync_buyer_statuses from raising on
    # every Celery Beat tick once this box has its first delivered lead.
    supports_status_sync = False

    # What build_payload() puts where the password goes. The real value is
    # substituted in inject_lead() and never appears in the audit trail.
    REDACTED_PASSWORD = REDACTED

    # Default-deny allowlist for LeadInjection.response_payload.
    #
    # ``redirectUrl`` is DELIBERATELY ABSENT and must stay absent. It is an
    # autologin URL — a bearer credential that logs the lead straight into
    # the broker's client area. Allowing it here would persist that
    # credential in plaintext JSON and render it to the affiliate via
    # affiliate_ui/templates/affiliate_ui/leads.html, which is exactly the
    # exposure this allowlist exists to prevent. If the funnel ever needs
    # the URL, it needs a deliberate storage decision (encrypted at rest,
    # TTL-aware, access-controlled) — NOT a quiet addition to this set.
    AUDIT_RESPONSE_ALLOWLIST = frozenset({'success', 'leadId'})

    # Mapped names (the RIGHT-hand side of field_mapping) whose value must
    # be normalized to a bare international MSISDN. Hypernet's docs are
    # explicit that the phone carries no plus sign; Lead.phone usually has
    # one, and is not guaranteed E.164 at all (see _normalize_msisdn).
    PHONE_KEYS = ('profile.phone',)

    def _static_fields(self) -> dict:
        """This box's fixed per-request constants (affc/bxc/vtc, and any
        funnel/landingURL/lang values that are properties of the box rather
        than of the lead).

        getattr rather than a plain attribute read because
        LeadBuyer.extra_payload_fields is not in the schema yet — the
        migration adding it is sequenced behind another in-flight one. Once
        it lands this becomes ``self.buyer.extra_payload_fields or {}``.
        """
        return dict(getattr(self.buyer, 'extra_payload_fields', None) or {})

    def get_or_create_password(self, lead) -> str:
        """The password Hypernet creates the lead's broker account with —
        generated ONCE, at first delivery, and stored encrypted at rest.

        Nexora has no consumer-supplied password and Hypernet's documented
        profile requires one, so it is synthesized: ``secrets.token_urlsafe``,
        encrypted with the same nexora.crypto helper that protects
        LeadBuyer.api_key_encrypted, and persisted to
        ``Lead.broker_password_encrypted``.

        Generated once rather than derived, because a derived password
        (e.g. HMAC over lead.pk) would let anyone holding SECRET_KEY compute
        every lead's broker credential from a sequential integer,
        retroactively and forever.

        Read-back, never regeneration: once a value is stored, an
        undecryptable one raises instead of silently minting a replacement.
        A regenerated password would diverge from what the broker actually
        stored, locking the lead out of the account with no record of why —
        exactly the failure mode SECRET_KEY rotation would otherwise cause
        (nexora.crypto is keyed off SECRET_KEY; see its module docstring).

        An UNSAVED lead (the console's Test Connection, admin_views.
        buyer_test_connection) gets an ephemeral password that is never
        persisted — nothing real is created at the buyer by that path.
        """
        stored = getattr(lead, 'broker_password_encrypted', '')
        if stored:
            raw = decrypt_secret(stored)
            if not raw:
                raise LeadBuyerError(
                    f'Stored broker password for lead #{lead.pk} could not be decrypted '
                    '(SECRET_KEY rotated?). Refusing to mint a replacement — the buyer '
                    'already has the original.')
            return raw

        raw = secrets.token_urlsafe(12)
        encrypted = encrypt_secret(raw)
        # hasattr on the model CLASS is the feature detect for "the field's
        # migration has landed" — Django installs a descriptor per field.
        # Until then the password is still sent, just not retained.
        if lead.pk and hasattr(type(lead), 'broker_password_encrypted'):
            from .models import Lead

            lead.broker_password_encrypted = encrypted
            # .touch(), never .update(): provisioning a broker credential is a
            # lead mutation, and LeadQuerySet.touch() is the one sanctioned
            # way to write a Lead (see its docstring — QuerySet.update()
            # leaves updated_at frozen and hides the change from the
            # ?updated_since= reconcile poll). Imported here rather than at
            # module scope both to avoid a circular import and so the write
            # reads as `Lead.objects...`, which is the shape
            # tests/test_no_untouched_lead_writes.py can actually see.
            Lead.objects.filter(pk=lead.pk).touch(broker_password_encrypted=encrypted)
        return raw

    def build_payload(self, lead) -> dict:
        """Hypernet's nested body: the base connector's flat mapped output
        reshaped by _set_path(), plus this box's static constants, plus the
        lead attributes the base cannot reach.

        The password is REDACTED here, deliberately. This method's result is
        what leadgen.tasks.inject_lead_task:87 records as
        LeadInjection.request_payload, and an audit trail does not need the
        credential to be useful — it needs to show what was sent, and a
        redaction marker shows exactly that. The real password is
        substituted in inject_lead() below, on the wire body only, so there
        is no code path in which build_payload() can leak it.

        Precedence is deliberate: a mapped LEAD value always wins over a
        static constant of the same name, so a box-level default (e.g. a
        fallback ``geo``) can never overwrite what we actually know about
        this specific lead.
        """
        payload = {}
        for key, value in self._static_fields().items():
            _set_path(payload, key, value)

        for key, value in super().build_payload(lead).items():
            if key in self.PHONE_KEYS:
                value, ambiguous = _normalize_msisdn(value)
                if ambiguous:
                    # Deliberately not raised: inject_lead_task calls this
                    # OUTSIDE its try block (tasks.py:87), so an exception
                    # here escapes the task unhandled — no LeadInjection
                    # update, no failure_reason, nothing for an operator to
                    # read. Warn and send; the fix belongs at intake.
                    logger.warning(
                        'Hypernet payload for lead #%s carries a national-format phone number '
                        '(no country code) — buyer will likely reject or misdial it.', lead.pk)
            _set_path(payload, key, value)

        # Outside MAPPABLE_LEAD_FIELDS — see the class docstring, point 4.
        if getattr(lead, 'ip', None):
            payload['ip'] = str(lead.ip)
        if getattr(lead, 'country_iso2', ''):
            payload['geo'] = lead.country_iso2
        _set_path(payload, 'profile.password', self.REDACTED_PASSWORD)

        return payload

    def inject_lead(self, lead) -> dict:
        """POST one lead, substituting the real password into the wire body,
        and capture the one-shot redirect from the response.

        This is the ONLY place the plaintext password exists —
        build_payload() (and therefore the audit trail, and therefore the
        console) sees the redaction marker instead. Overridden rather than
        folded into build_payload() precisely so that separation is
        structural rather than a convention someone has to remember.

        The redirect is captured HERE, rather than at the task's response
        handling, for two reasons: it is Hypernet-specific and does not
        belong in the shared task, and Hypernet returns it only on
        submission — never on a status check — so this is the one moment it
        is ever available."""
        payload = self.build_payload(lead)
        _set_path(payload, 'profile.password', self.get_or_create_password(lead))
        response = self._request('POST', self.box_type.single_endpoint_path, json=payload)
        self.capture_redirect_url(lead, response)
        return response

    def capture_redirect_url(self, lead, response) -> None:
        """Store the buyer's one-shot ``redirectUrl`` encrypted, stamped with
        the moment it was captured so Lead.get_broker_redirect_url() can
        expire it.

        Deliberately best-effort: a lead that was accepted must never be
        recorded as a failure because we could not persist a 3-minute
        redirect. Any error here is logged and swallowed — the injection
        outcome is what matters, and the redirect is a convenience with two
        independent expiry mechanisms behind it.

        Skipped for an UNSAVED lead (the console's Test Connection probe) —
        there is nothing to attach it to, and no real consumer to redirect.
        """
        if not isinstance(response, dict):
            return
        url = response.get('redirectUrl')
        if not url or not lead.pk:
            return
        from django.utils import timezone

        from .models import Lead

        if not hasattr(Lead, 'broker_redirect_url_encrypted'):
            # Connector deployed ahead of its migration — send the lead, skip
            # the convenience, do not crash a delivery over it.
            logger.warning('Lead.broker_redirect_url_encrypted missing; redirect not stored.')
            return
        try:
            now = timezone.now()
            encrypted = encrypt_secret(str(url))
            lead.broker_redirect_url_encrypted = encrypted
            lead.broker_redirect_captured_at = now
            # .touch(), not .update() — see LeadQuerySet.touch's docstring;
            # a lead whose state changed without moving updated_at is
            # invisible to the ?updated_since= reconcile poll.
            Lead.objects.filter(pk=lead.pk).touch(
                broker_redirect_url_encrypted=encrypted, broker_redirect_captured_at=now)
        except Exception:  # noqa: BLE001 — never fail a delivered lead over this
            logger.exception('Could not store broker redirect for lead #%s', lead.pk)

    def inject_batch(self, leads):
        """Hypernet documents no batch endpoint. The base class would happily
        POST ``{"leads": [...]}`` to whatever batch path a BoxType had
        configured, so refuse explicitly rather than relying on
        ``batch_max_size=1`` staying set."""
        raise LeadBuyerError('Hypernet has no batch injection endpoint; inject leads one at a time.')

    def parse_injection_result(self, response: dict) -> tuple[str, str, str]:
        """``{"success", "redirectUrl", "leadId"}`` -> our
        (external_id, status, failure_reason).

        Note what is NOT returned: ``redirectUrl``. It survives only because
        leadgen.tasks.inject_lead_task stores the whole response dict on
        LeadInjection.response_payload — this tuple has no room for it. See
        the integration notes; exposing an autologin URL is a deliberate
        product decision, not something to smuggle through here.
        """
        if not isinstance(response, dict) or not response:
            # _request() returns {} for a 2xx with an empty body. Hypernet
            # documents a JSON 201, so an empty body is unexplained — not a
            # success.
            return '', 'failed', 'Empty response body from Hypernet (expected a JSON result).'

        if response.get('success'):
            return str(response.get('leadId') or ''), 'delivered', ''

        # Hypernet's error shape isn't documented beyond the success case —
        # capture whatever is present rather than assuming a specific key.
        detail = response.get('message') or response.get('error') or str(response)
        return '', 'failed', str(detail)[:255]

    def fetch_lead_statuses(self, external_ids) -> dict:
        """Not implemented — deliberately.

        Hypernet's GET /api/external/integration/lead filters by date window
        (``skip``/``take``/``from``/``to``), not by an ID list, so the base
        class's ``Ids=``/``PageSize=`` call would be accepted and return an
        unrelated page of rows. Status sync for this box needs a
        pull-a-window-and-match-on-leadId approach instead.

        Raising is the point: leadgen.tasks.sync_buyer_statuses_for_buyer
        catches only LeadBuyerError around this call, so this propagates to
        sync_buyer_statuses' per-buyer ``except Exception`` and is logged
        loudly, once per beat tick, from the moment this box has its first
        delivered injection. That noise is the intended signal — a silently
        wrong implementation would be worse.
        """
        raise NotImplementedError(
            'Hypernet status sync needs a date-range-based approach (pull a window, match on '
            'leadId), not the base class Ids filter — confirm requirements before building.')

    def parse_status_sync_results(self, response: dict) -> list[dict]:
        """Not implemented — see fetch_lead_statuses(). Overridden so nobody
        half-wires status sync by supplying a fetch and inheriting a parser
        written for op-brandy's ``{"items": [...]}`` shape (Hypernet returns
        ``{"count": N, "rows": [...]}`` with a different row shape)."""
        raise NotImplementedError(
            'Hypernet status-sync parsing is not implemented — its rows carry registration.status/'
            'isDeposited/depositedAt, not op-brandy\'s deposit/status.name.')
