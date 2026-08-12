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
from datetime import datetime, time, timedelta
from datetime import timezone as dt_timezone
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
    4xx a connector calls       CapacityError       retry on the LONG
    "no capacity" (see                              schedule, or cascade if
    is_capacity_error)                              a next buyer exists
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

    NOT every 4xx is this — see LeadBuyerCapacityError for the exception a
    connector can carve out.
    """


class LeadBuyerCapacityError(LeadBuyerError):
    """The buyer refused to ROUTE this lead — they never evaluated it.

    A 4xx that means "I have nowhere to put this right now": no desk/hub
    open for the lead's geo, a cap filled, a destination paused. The
    distinction from LeadBuyerRejectedError is not cosmetic — it is the
    difference between a verdict on THIS LEAD and a statement about the
    buyer's own current state:

    * A rejection is a property of the payload. The identical payload will
      be refused identically in 60 seconds, so retrying is pure latency.
    * A capacity refusal is a property of the BUYER, and it is temporary by
      construction. Caps reset, paused desks resume, working-hours routing
      opens. The identical payload may well be accepted later, and the lead
      is otherwise perfectly good.

    Treating the second as the first silently destroys good leads. That is
    not hypothetical: on 2026-08-07 ChainPulse sent 10 real Brazilian leads
    to Hypernet-desperados in 40 minutes and every one was answered
    ``[404] {"error": "No hubs available for this lead."}`` — an hour after
    the box had happily accepted a lead with a byte-identical payload. All
    10 landed on Rejected with Attempts: 1 and no way back.

    SUBCLASSES THE BASE, NOT LeadBuyerRejectedError — deliberately, and it
    matters. A handler that has never heard of this class falls through to
    its ``except LeadBuyerError`` and retries, which is the safe default. If
    this subclassed RejectedError instead, every existing terminal handler
    would silently swallow it and the distinction would buy nothing. It is a
    SIBLING of RejectedError, so the two are order-independent in an
    ``except`` chain; only the base must come after both.

    Never raised on the connector's own judgement of what a status code
    "probably" means — a connector opts in per box by overriding
    is_capacity_error(), which is default-deny.
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

    def is_capacity_error(self, status_code: int, response) -> bool:
        """Is this failing 4xx a "no capacity right now", rather than a
        verdict on the lead? See LeadBuyerCapacityError.

        DEFAULT-DENY, and it stays that way. Every box says "full" in its own
        words on its own status code, and there is no cross-vendor convention
        to generalise from — so the base class claims nothing and every
        existing buyer keeps today's exact behaviour. A connector opts in for
        ITS box only, by overriding this.

        Consulted only for a 4xx that is not 429 (429 is already retryable),
        and only from _request(). `response` is the raw requests.Response, so
        an override can read the body it needs; it MUST NOT raise — an
        override that blows up on an unexpected body would turn every
        rejection into a crash, so treat anything unrecognised as False.
        """
        return False

    def _is_capacity_error(self, status_code: int, response) -> bool:
        """is_capacity_error() with its "must not raise" contract actually
        enforced, rather than left to each override to remember.

        A subclass reads a buyer's error body here — the least predictable
        input in the system. If an override throws on some shape nobody
        anticipated, the exception would escape _request() from inside its
        own error handling and replace a clean rejection with a crash, on
        the one path that exists to classify failures. Falling back to False
        degrades to today's behaviour (terminal rejection), which is the
        safe direction: a lead that cascades when it could have waited is
        recoverable; a task that dies mid-classification is not.
        """
        try:
            return bool(self.is_capacity_error(status_code, response))
        except Exception:  # noqa: BLE001 — see docstring; never crash the classifier
            logger.exception(
                'is_capacity_error() raised for buyer %s on a %s; treating as a rejection.',
                self.buyer.slug, status_code)
            return False

    def extra_auth_headers(self) -> dict:
        """Additional headers every request to this box must carry, beyond
        the single credential BoxType.auth_type describes.

        Empty by default, so nothing changes for op-brandy or Hypernet.
        BoxType.auth_type models exactly ONE credential in one place, which
        is all most boxes need; TrackBox needs three headers at once and
        overrides this rather than reimplementing _request() and losing its
        rate limiting, timeout bounding and error classification.

        Returned values are merged into the headers AFTER the BoxType's own
        auth header, so an override cannot silently displace the primary
        API key — a box wanting a different primary credential should change
        its BoxType instead.

        MUST NOT be logged or recorded anywhere: like the API key, whatever
        this returns is a credential. _request() keeps it off the audit
        trail by building LeadInjection.request_payload from mapped lead
        fields only, never from the outgoing headers.
        """
        return {}

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

        headers.update(self.extra_auth_headers())

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
                # Carve-out first: a 4xx meaning "no room right now" is about
                # the BUYER's state, not about this lead, and clears on its
                # own — see LeadBuyerCapacityError. Default-deny, so a box
                # that has not opted in falls straight through to the
                # rejection below exactly as before.
                if self._is_capacity_error(code, resp):
                    raise LeadBuyerCapacityError(detail, status_code=code)
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


def _first_present(row: dict, *keys):
    """The first of ``keys`` present in ``row`` with a non-empty value, else
    None.

    For reading a box whose response schema is undocumented: each field is
    expressed as the set of spellings it plausibly arrives under, and the
    reader survives whichever one the box actually uses. ``False`` and ``0``
    count as PRESENT — a deposit flag of False is a real answer, not a
    missing one — so the emptiness test is deliberately against None/''/[]
    rather than plain falsiness.
    """
    for key in keys:
        value = row.get(key)
        if value not in (None, '', []):
            return value
    return None


def _truthy(value) -> bool:
    """Whether an undocumented box's flag means yes.

    JSON booleans, numbers and the string spellings ("1", "true", "yes", "Y")
    that boxes of this class use interchangeably for the same flag. Anything
    unrecognised is False, which is the safe direction for the one caller
    that matters: TrackBoxConnector reads a DEPOSIT flag through this, and a
    lead wrongly marked as deposited bills an affiliate for a conversion
    that did not happen.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value or '').strip().lower() in {'1', 'true', 'yes', 'y', 't'}


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


class BrokerPasswordMixin:
    """A password for boxes that require one in the signup body.

    Extracted from HypernetConnector when TrackBox turned out to need the
    identical thing (its ``/api/signup/procform`` body carries a
    ``password``): both boxes create a real broker account for the lead, and
    neither Nexora nor the affiliate ever collects a consumer password.

    What replaces it in an audit trail. The real value is substituted into
    the wire body by the connector's own inject_lead(), so build_payload()
    — and therefore LeadInjection.request_payload, and therefore the
    console — only ever sees the marker.
    """

    REDACTED_PASSWORD = REDACTED

    def get_or_create_password(self, lead) -> str:
        """The password the lead's broker account is provisioned with —
        generated ONCE, at first delivery, and stored encrypted at rest.

        Neither box collects a consumer-supplied password and both require
        one, so it is synthesized: ``secrets.token_urlsafe``, encrypted with
        the same nexora.crypto helper that protects
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

        THE FIELD IS SHARED ACROSS BOXES, and that is correct: a lead is
        only ever sold to one buyer at a time, so the stored password
        belongs to whichever box actually provisioned the account. A lead
        that cascades from one box to another after a rejection reuses the
        same password at the second box, which is harmless — the first box
        never created an account for it.

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


class DateWindowStatusSyncMixin:
    """Status sync for a box whose read endpoint has NO id filter.

    Extracted from HypernetConnector when TrackBox turned out to have the
    same shape of problem. Both boxes expose a read endpoint that filters
    only by a DATE RANGE over the lead's REGISTRATION date — neither offers
    "give me these ids" and neither offers "give me what changed since".

    THE TRAP THIS EXISTS TO AVOID: the intuitive "pull the last hour of
    changes" is wrong on such a box. A lead that registered in March and
    deposits today appears in a MARCH window, never in a today window.
    Written that way the sync looks perfectly healthy and silently misses
    almost every deposit — the event that actually bills.

    What we do instead: our own injection timestamp is the closest thing we
    have to their registration date, so we window by THAT, generously
    padded (STATUS_SYNC_WINDOW_PAD). The requested ids are grouped by the
    UTC day they were injected, those day windows are padded and then
    coalesced where they overlap (_merged_windows), and each resulting
    range is pulled once. Days with no leads are never requested, so cost
    scales with how many contiguous RUNS of days the caller's chunk spans,
    not with how far back the oldest lead is — which is also why a backfill
    of arbitrarily old leads costs about the same per lead as a live sync.

    A subclass supplies the two box-specific pieces: _pull_window(), which
    knows that box's pagination, and ROWS_KEY, the envelope key its rows
    arrive under (and which its own parse_status_sync_results reads back).
    """

    # Widen each window by this much at both ends, because the box's
    # registration date is NOT our injection timestamp and the gap is not
    # small. See HypernetConnector for the measured 18h24m skew that set
    # this figure; a box with its own evidence overrides it.
    STATUS_SYNC_WINDOW_PAD = timedelta(hours=48)

    # Runaway guard, so a misbehaving page count cannot spin a worker forever.
    STATUS_SYNC_MAX_PAGES = 50

    # The envelope key rows come back under, for both the value this returns
    # and the subclass's parse_status_sync_results.
    ROWS_KEY = 'rows'

    def _row_id(self, row) -> str:
        """The external id on one row of this box's read endpoint.

        Overridable because the read side and the write side of these boxes
        routinely disagree about the name — Hypernet RESPONDS to an
        injection with ``leadId`` but keys the same value as ``id`` when
        reading, and reading the wrong one silently yields nothing while
        every lead looks absent.
        """
        return str((row or {}).get('id') or '')

    def _pull_window(self, start, end):
        """Every row this box has in [start, end], pagination included.

        Abstract: pagination is the one thing these boxes never share
        (Hypernet pages by skip/take against a total count, TrackBox by an
        incrementing page number against a last-page marker).
        """
        raise NotImplementedError

    def fetch_lead_statuses(self, external_ids) -> dict:
        """Pull statuses for `external_ids` by DATE WINDOW, matching on row id.

        Returns this box's own envelope narrowed to the requested ids:
        ``{'count': n, <ROWS_KEY>: [...]}``. Rows are deduplicated by id
        because STATUS_SYNC_WINDOW_PAD makes adjacent days overlap by
        design.

        A lead the box still does not return after all that is logged as a
        discrepancy rather than guessed at — see the `missing` branch.
        """
        from .models import LeadInjection

        wanted = {str(e) for e in (external_ids or []) if e}
        if not wanted:
            return {'count': 0, self.ROWS_KEY: []}

        # Their registration date is not stored on our side; our injection
        # timestamp is the closest thing we have to it, and
        # STATUS_SYNC_WINDOW_PAD covers the difference. Scoped to this buyer
        # so a shared external_id string can never pull another box's window.
        injected_at = LeadInjection.objects.filter(
            buyer=self.buyer, external_id__in=wanted
        ).values_list('external_id', 'created_at')

        days = {created.astimezone(dt_timezone.utc).date() for _, created in injected_at}
        if not days:
            # Nothing of ours to look up — no injection rows for these ids on
            # this buyer. Not an error: return empty rather than pulling a
            # window we have no basis for.
            logger.warning(
                '%s status sync: no injections on buyer %s for %s external_id(s); '
                'nothing to pull.', type(self).__name__, self.buyer.slug, len(wanted))
            return {'count': 0, self.ROWS_KEY: []}

        rows_by_id = {}
        for start, end in self._merged_windows(days):
            for row in self._pull_window(start, end):
                row_id = self._row_id(row)
                if row_id in wanted:
                    rows_by_id[row_id] = row

        missing = wanted - rows_by_id.keys()
        if missing:
            # NOT an error, and deliberately not raised: a lead we delivered
            # that their read endpoint does not return is a real, open
            # discrepancy (see docs/hypernet-status-endpoint.md, where 2 of
            # the first 3 deliveries were absent from the buyer's side
            # entirely despite their API returning success and an id for
            # each). Absence cannot be read as "no change" OR as "lost" — so
            # log it plainly and sync what we did get.
            logger.warning(
                '%s status sync: %s of %s requested lead(s) absent from buyer %s: %s',
                type(self).__name__, len(missing), len(wanted), self.buyer.slug,
                sorted(missing)[:20])

        return {'count': len(rows_by_id), self.ROWS_KEY: list(rows_by_id.values())}

    def _merged_windows(self, days):
        """The padded windows for `days`, with overlapping ones coalesced.

        Each day becomes [midnight - PAD, end-of-day + PAD]. At a 48h pad two
        consecutive days overlap by about four of their five days, so pulling
        them separately would re-fetch the same rows several times over and
        multiply requests against a box that already answers slowly. Merging
        first makes a contiguous run of days cost one range instead of one per
        day, which is what keeps a wide pad affordable.

        Returns (start, end) tuples in ascending order. Purely arithmetic — no
        I/O — so the merge itself is cheap and unit-testable. The result set is
        identical to pulling each day separately: the caller keys rows by id
        and keeps only the ones it asked for.
        """
        windows = sorted(
            (
                datetime.combine(day, time.min, tzinfo=dt_timezone.utc) - self.STATUS_SYNC_WINDOW_PAD,
                datetime.combine(day, time.max, tzinfo=dt_timezone.utc) + self.STATUS_SYNC_WINDOW_PAD,
            )
            for day in days
        )
        merged = []
        for start, end in windows:
            if merged and start <= merged[-1][1]:
                # Overlaps (or exactly abuts) the run we're building — extend
                # it rather than opening a second request for the same span.
                merged[-1][1] = max(merged[-1][1], end)
            else:
                merged.append([start, end])
        return [(start, end) for start, end in merged]


class HypernetConnector(BrokerPasswordMixin, DateWindowStatusSyncMixin, LeadBuyerConnector):
    """Connector for Hypernet-CRM-style boxes (HTN-AFF-SDK) — the second box
    onboarded after op-brandy, and the first that genuinely needed its own
    connector_class rather than just a LeadBuyer row.

    Five things about Hypernet the generic connector cannot express:

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

    5. **Status sync by date window.** Their GET has no ID filter —
       id/ids/Ids/leadId/leadIds/externalId, every variant 400s (probed; see
       docs/hypernet-status-endpoint.md) — and its date window filters on
       REGISTRATION date, not on when a status changed. The base class's
       ``Ids=`` call therefore cannot work here. DateWindowStatusSyncMixin
       supplies the replacement (window by our own injection date, padded and
       coalesced); this class supplies only the two box-specific pieces,
       _pull_window() for their skip/take pagination and the ``id``-not-
       ``leadId`` row key inherited from the mixin's default _row_id().
    """

    # Measured against the live desperados box: a successful POST took 11.8s,
    # and an earlier attempt exceeded the 15s default outright. Their box is
    # simply slow to answer. At the default this intermittently produced a
    # read timeout -> AMBIGUOUS -> quarantine for leads that had NOT actually
    # been rejected, each needing a human to check their system by hand.
    # 60s leaves real headroom over the observed latency while still bounding
    # a hung endpoint well inside a Celery worker's tolerance.
    default_timeout = 60

    # Status sync works for this box, but not the way the base class does it
    # — see fetch_lead_statuses() and docs/hypernet-status-endpoint.md.
    supports_status_sync = True

    # Their GET caps `take` at 500 — 501 returns 400. Their `count` is the
    # TOTAL matching rows, not the page size, so paging runs until `count` is
    # consumed rather than until a page comes back short.
    STATUS_SYNC_PAGE_SIZE = 500

    # Widen each window by this much at both ends, because their createdAt is
    # NOT our injection timestamp and the gap is not small.
    #
    # This was 1 hour, justified by a single observed sample (0.8s on lead 29).
    # Reconciling ChainPulse against desperados on 2026-08-07 found the sample
    # was not representative: lead 22 was injected 08-06 11:42 and carries
    # their createdAt of 08-07T06:06Z — 18h24m later, across a UTC day
    # boundary. Its window was built around 08-06 and therefore never saw it,
    # so it would never have received a status, silently, while the sync
    # logged as healthy. 48h clears the observed skew by better than 2x in
    # both directions.
    #
    # The cost is bounded by DateWindowStatusSyncMixin._merged_windows(): a
    # wide pad makes adjacent days' windows overlap almost entirely, so they
    # are merged into one range before any request goes out. Widening the pad
    # therefore costs roughly one extra window's worth of rows per contiguous
    # run of days, not a multiple of every day pulled. Too NARROW silently
    # drops leads; that is the failure mode worth paying to avoid.
    STATUS_SYNC_WINDOW_PAD = timedelta(hours=48)

    # Runaway guard. At 500/page this is 25k rows for a single merged window —
    # orders of magnitude past anything this box does, even at a 48h pad. It
    # exists so a misbehaving `count` cannot spin a Celery worker forever.
    STATUS_SYNC_MAX_PAGES = 50

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

    # The one 4xx from this box that means "no room right now" rather than
    # "no" — see is_capacity_error() below and LeadBuyerCapacityError.
    CAPACITY_ERROR_STATUS = 404
    CAPACITY_ERROR_PATTERN = re.compile(r'no\s+hubs?\s+available', re.IGNORECASE)

    # Mapped names (the RIGHT-hand side of field_mapping) whose value must
    # be normalized to a bare international MSISDN. Hypernet's docs are
    # explicit that the phone carries no plus sign; Lead.phone usually has
    # one, and is not guaranteed E.164 at all (see _normalize_msisdn).
    PHONE_KEYS = ('profile.phone',)

    def is_capacity_error(self, status_code: int, response) -> bool:
        """True for desperados' ``[404] {"error": "No hubs available for this
        lead."}`` — their router saying it has no open hub for this lead's
        geo/vertical right now, which is temporary. Everything else this box
        can answer stays a rejection.

        WHY THIS MATCHES ON THEIR MESSAGE TEXT, which is normally a bad idea:
        there is nothing better to match on. The status code alone is too
        broad — a 404 is also what a wrong single_endpoint_path returns, and
        retrying that for hours instead of failing loudly would hide a
        misconfiguration. They send no error code on this envelope
        (``{"success", "redirectUrl", "leadId", "error"}``; their `code` field
        appears only on validation errors, which come back as 400s shaped
        ``{"message", "code", "statusCode"}``). So the message is the only
        signal that separates the two.

        What makes it acceptable here is the direction it fails in. If
        Hypernet rewords the string, this returns False and the lead takes
        the CURRENT path — a terminal rejection. That is today's behaviour,
        not a new failure mode: we lose the improvement, quietly, and nothing
        breaks. The pattern is deliberately loose about whitespace and
        singular/plural for the same reason, and deliberately does NOT anchor
        or match the whole message, so a suffix like "...for this lead
        (geo: BR)" still hits.

        The opposite bias — matching every 404 — fails in the dangerous
        direction, so it is not what this does.
        """
        if status_code != self.CAPACITY_ERROR_STATUS:
            return False
        try:
            body = response.json()
        except ValueError:
            # Their 404s are JSON. A non-JSON one is some intermediary
            # (proxy, WAF, wrong host) answering instead of the box, which is
            # not a statement about capacity.
            return False
        if not isinstance(body, dict):
            return False
        return bool(self.CAPACITY_ERROR_PATTERN.search(str(body.get('error') or '')))

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

    @staticmethod
    def _window_param(dt) -> str:
        """Their accepted wire format. Full ISO-8601 in UTC with a literal Z —
        date-only also parses, but a whole-day bucket is not what we want, and
        a unix epoch returns 500 rather than 400 (their input handling is not
        defensive, so send only what is known good)."""
        return dt.astimezone(dt_timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

    def _pull_window(self, start, end):
        """Every row in [start, end], following their skip/take pagination.

        Their ``count`` is the total matching, not the page length, so this
        pages until count is consumed. Stops early on a short/empty page too,
        so a wrong count cannot loop; STATUS_SYNC_MAX_PAGES bounds it either
        way."""
        collected = []
        skip = 0
        for _ in range(self.STATUS_SYNC_MAX_PAGES):
            response = self.fetch_leads(**{
                'from': self._window_param(start),
                'to': self._window_param(end),
                'skip': skip,
                'take': self.STATUS_SYNC_PAGE_SIZE,
            })
            rows = (response or {}).get('rows') or []
            collected.extend(rows)
            total = (response or {}).get('count')
            if not rows or not isinstance(total, int) or len(collected) >= total:
                return collected
            skip += len(rows)
        logger.warning(
            'Hypernet status sync: hit STATUS_SYNC_MAX_PAGES (%s) for window %s..%s on buyer %s; '
            'results may be incomplete.',
            self.STATUS_SYNC_MAX_PAGES, start, end, self.buyer.slug)
        return collected

    def parse_status_sync_results(self, response: dict) -> list[dict]:
        """Hypernet rows -> the shared status-sync contract.

        Their row shape shares nothing with op-brandy's beyond intent, which is
        why this override exists:

        ==================  ====================================================
        Contract key        Hypernet source
        ==================  ====================================================
        external_id         ``id``          NOT ``leadId``
        buyer_status        ``registration.status``
        deposit             ``isDeposited``
        updated_at          ``depositedAt``, or '' — see below
        country_iso2        ``geo``         already alpha-2
        ==================  ====================================================

        ``id`` vs ``leadId`` is a genuine trap: injection RESPONDS with
        ``leadId``, but the read side keys the same value as ``id``. Reading
        ``leadId`` off a row silently yields nothing and every lead looks
        absent.

        ``registration.status`` is their normalized vocabulary ('deposited');
        ``rawStatus`` beside it is the broker's own free text ('Test Lead' on
        the QA box) and varies per broker configuration. The normalized one is
        what default_status_mapping should be keyed on, so that is what this
        returns.

        THE updated_at COMPROMISE: their rows carry no general updated-at.
        Only ``createdAt`` and ``depositedAt`` exist, and depositedAt only once
        a deposit has happened. So a non-deposit status change has no timestamp
        available at all, and this returns '' for it — which
        tasks._parse_buyer_timestamp turns into None, leaving
        buyer_status_updated_at unset. That is deliberate: None reads as "we do
        not know when", whereas stamping sync time would assert the status
        changed at the moment we happened to poll, which is false. A non-empty
        buyer_status alongside a null timestamp is the honest encoding of what
        this endpoint can actually tell us. Deposits — the ones that bill — do
        get a real timestamp. Revisit if Hypernet exposes an updated-at.
        """
        results = []
        for row in (response or {}).get('rows') or []:
            external_id = str(row.get('id') or '')
            if not external_id:
                continue
            registration = row.get('registration') or {}
            results.append({
                'external_id': external_id,
                'buyer_status': registration.get('status') or '',
                'deposit': bool(row.get('isDeposited')),
                'updated_at': row.get('depositedAt') or '',
                'country_iso2': (row.get('geo') or '')[:2],
            })
        return results


# --- TrackBox (Tigloo) ---------------------------------------------------------

class TrackBoxConnector(BrokerPasswordMixin, DateWindowStatusSyncMixin, LeadBuyerConnector):
    """Connector for TrackBox-by-Tigloo boxes — the third box onboarded,
    after op-brandy and Hypernet.

    Public docs: https://intercom.help/tigloo/en/articles/9349579-trackbox-api-documentation
    They cover REQUEST shapes only; every response fact below was established
    by probing a live instance. See docs/trackbox-integration.md.

    Four things about TrackBox the generic connector cannot express:

    1. **FAILURES ARRIVE AS HTTP 200.** This is the one that matters most,
       and it is not in their docs. Every outcome — including a flat auth
       rejection — comes back ``200 OK`` with the real result in the body::

           {"status": false,
            "message": "Cant Pull Data, please contact support with caseID: ...",
            "code": 401}

       The base connector classifies on the HTTP status line (see
       LeadBuyerError's table), so on this box it would read a 401 as a
       SUCCESS and hand a credentials failure to parse_injection_result as
       though the buyer had answered. _raise_for_soft_error() below restores
       the classification from the body.

    2. **Three auth headers, not one.** ``x-trackbox-username`` /
       ``x-trackbox-password`` / ``x-api-key``. BoxType.auth_type models a
       single credential, so the API key uses that as normal and the other
       two come from LeadBuyer.extra_credentials_encrypted via
       extra_auth_headers() — encrypted at rest, never in the audit trail.

    3. **Static per-buyer constants.** Every signup body carries this box's
       ``ai`` (affiliate id), ``ci`` (campaign id) and ``gi``, which their
       docs describe only as "ask from your trackbox partner". They are
       properties of the BUYER, not of the lead, so they live in
       LeadBuyer.extra_payload_fields alongside ``so`` and ``lg`` — nothing
       build_payload() maps.

    4. **The read endpoint is a POST with a date window and no id filter.**
       Same shape of problem Hypernet has, so status sync comes from
       DateWindowStatusSyncMixin; this class supplies only their page-number
       pagination (_pull_window) and their ``data``/``meta`` envelope.

    A note on what is deliberately NOT claimed here: their docs publish no
    response schema at all, and the credentials in hand cannot complete a
    request (see the module doc referenced above — the ``x-api-key`` is
    still outstanding). So every response-side key name below is a
    CANDIDATE SET rather than a single known key, and each one logs loudly
    when nothing matches. That is the honest encoding of what is known, and
    it makes the first real delivery self-diagnosing instead of silent.
    """

    # Their pull path answers in ~0.35s, but that is the auth-reject
    # short-circuit and is not representative. /api/signup/procform proxies
    # SYNCHRONOUSLY to the brand's own API and returns the brand's response
    # embedded in its own, so a push costs TrackBox's latency plus the
    # brand's — the same reason HypernetConnector runs at 60s after
    # measuring 11.8s there.
    #
    # This matters more than an ordinary tuning knob: a timeout that fires
    # while the brand is still processing produces an AMBIGUOUS outcome and
    # quarantines a lead that may well have been accepted. Revise this from
    # observed push latency once real traffic has flowed, not before.
    default_timeout = 45

    supports_status_sync = True

    # Their pull envelope is {"data": [...], "meta": {...}} — see
    # _pull_window(). DateWindowStatusSyncMixin returns rows under this key
    # and parse_status_sync_results() reads them back from it.
    ROWS_KEY = 'data'

    # meta.limit in their own documented example. Their pagination is a
    # 1-based page NUMBER against meta.lastPage, not an offset.
    STATUS_SYNC_PAGE_SIZE = 500

    # Their pull filters on registration date, so the window is built from
    # our injection timestamp — see DateWindowStatusSyncMixin. Inheriting
    # Hypernet's measured 48h rather than guessing a tighter one: too NARROW
    # silently drops leads, which is the failure mode worth paying to avoid,
    # and the cost of a wide pad is bounded by window coalescing.
    STATUS_SYNC_WINDOW_PAD = timedelta(hours=48)

    # Keys under which a successful signup response may carry the id we must
    # store as LeadInjection.external_id — the handle every later status
    # pull matches on. Ordered by how likely each is; the first present,
    # non-empty one wins.
    #
    # A LIST rather than one key because their docs publish no response
    # schema. Getting this wrong is not cosmetic: an empty external_id means
    # the lead is excluded from every future status sync
    # (tasks.sync_buyer_statuses filters .exclude(external_id='')), so a
    # deposit would never come back. Hence the loud log in
    # _extract_external_id() rather than a silent ''.
    #
    # CONFIRMED against the live Traffix box on 2026-08-12: a real accepted
    # lead carries all three of customerId / uniqueid / id, holding the SAME
    # value, nested at ``addonData.data`` — see RESPONSE_ID_SCOPES.
    EXTERNAL_ID_KEYS = ('orderid', 'orderId', 'customerid', 'customerId',
                        'leadOrderId', 'uniqueid', 'id')

    # Where in the response an id may be found, as paths walked in order.
    # ``()`` is the top level.
    #
    # ``('addonData', 'data')`` is where the live box actually puts it, and
    # nothing in their documentation suggests it. The first real delivery
    # returned an id ONLY there — the top level and ``data`` both had none,
    # so a search of those alone came back empty and logged the lead as
    # unsyncable. Do not narrow this list on the assumption that a shallower
    # scope is "the" location.
    RESPONSE_ID_SCOPES = ((), ('data',), ('addonData', 'data'), ('addonData',))

    # Same problem on the read side, and the same trap Hypernet has: a box's
    # write and read sides routinely disagree about the name of the same
    # value. Reading the wrong one yields nothing while every lead looks
    # absent, so this is a candidate set too.
    ROW_ID_KEYS = EXTERNAL_ID_KEYS

    # Body `code` values that are a verdict on OUR CREDENTIALS rather than
    # on the lead. Deliberately RETRYABLE (plain LeadBuyerError), not
    # LeadBuyerRejectedError: an auth failure is a property of this
    # platform's configuration, not of the payload, and it is fixable — once
    # the key is corrected the identical lead succeeds. Cascading it would
    # burn a good lead through the whole buyer chain over a typo in a
    # credential, which is exactly the loss LeadBuyerCapacityError exists to
    # prevent in the other direction.
    AUTH_ERROR_CODES = frozenset({401, 403})

    # Their wording for "no room right now", matched the same way and for
    # the same reasons as HypernetConnector.CAPACITY_ERROR_PATTERN: loose
    # about whitespace and plurals, unanchored, and failing CLOSED (a
    # reword returns False and the lead takes today's path — a terminal
    # rejection — rather than retrying forever against a real misconfig).
    CAPACITY_ERROR_PATTERN = re.compile(
        r'(no\s+(available\s+)?(box|boxes|brand|brands|integration|integrations)'
        r'|cap(acity)?\s+(is\s+)?(full|reached|exceeded)'
        r'|daily\s+limit)', re.IGNORECASE)

    # Their wording for "we already have this person".
    DUPLICATE_PATTERN = re.compile(r'(duplicat|already\s+(exist|registered)|exists)', re.IGNORECASE)

    # Mapped names whose value must be a bare international MSISDN — their
    # own example is "4407012259886", no plus sign.
    PHONE_KEYS = ('phone',)

    # Default-deny allowlist for LeadInjection.response_payload.
    #
    # Allowlisting a key means "RECURSE INTO IT", not "publish it" — see
    # _sanitize_for_audit — so a container key here is safe and every
    # unrecognised child inside it is still redacted. That is what keeps
    # their autologin URLs out of the audit trail without this code having
    # to know which of several names they arrive under.
    #
    # A SCALAR key is the exact opposite, and that distinction cost a real
    # leak. ``data`` was originally listed here on the assumption it was a
    # container. On the live box a successful signup returns ``data`` as a
    # STRING — the autologin URL itself — and allowlisting a scalar
    # publishes it verbatim. It landed unredacted on response_payload, which
    # affiliate_ui/templates/affiliate_ui/leads.html renders to affiliates.
    # An autologin URL is a bearer credential that logs the lead straight
    # into the broker's client area.
    #
    # ``data`` stays here, but it is no longer TRUSTED here: it must also
    # appear as a container to survive, because sanitize_response_for_audit()
    # below replaces any SCALAR value under these names before the walk
    # begins. Keeping it allowlisted is what lets the nested
    # ``addonData.data`` object be recursed into — so customerId/uniqueid/id
    # survive while their siblings ``loginURL`` and ``brokerUrl`` are
    # redacted by default-deny — while the top-level scalar ``data`` is
    # neutralised by SHAPE rather than by name.
    #
    # THE GENERAL RULE, for the next box: only allowlist a key you know to
    # be a CONTAINER. A key whose value might be a scalar credential must be
    # handled structurally, never by trusting its name.
    #
    # ``message`` is allowed deliberately: on a failure it is the only
    # operator-readable explanation the box gives, and it carries their
    # support caseID, which is what a human needs to open a ticket. It is
    # not a credential.
    AUDIT_RESPONSE_ALLOWLIST = frozenset(
        {'status', 'code', 'message', 'data', 'addonData'} | set(EXTERNAL_ID_KEYS))

    # Keys whose value is a bare autologin URL rather than an object, and so
    # can never be made safe by recursing into them. Replaced wholesale
    # before the default-deny walk — see sanitize_response_for_audit().
    SCALAR_CREDENTIAL_KEYS = ('data', 'loginURL', 'fallbackURL', 'brokerUrl')

    # --- auth ------------------------------------------------------------------

    def extra_auth_headers(self) -> dict:
        """The username/password pair that rides alongside the API key.

        Stored Fernet-encrypted in LeadBuyer.extra_credentials_encrypted
        (never extra_payload_fields, which is plaintext and rendered in the
        console). The API key itself is NOT here — it goes through
        BoxType.auth_type/auth_param_name like every other box's.

        Raises rather than sending a half-authenticated request. Because
        this box answers 200 to everything, a missing credential would come
        back as an ordinary-looking body and be recorded against the LEAD as
        a rejection — burning a real lead to report a configuration error.
        A raised LeadBuyerError is retryable and says what is wrong.
        """
        credentials = self.buyer.get_extra_credentials()
        username = str(credentials.get('username') or '').strip()
        password = str(credentials.get('password') or '')
        if not username or not password:
            raise LeadBuyerError(
                f'TrackBox buyer {self.buyer.slug!r} has no username/password configured '
                '(LeadBuyer.extra_credentials_encrypted). Set them with '
                '`manage.py seed_trackbox_box --buyer`, or the console\'s "Extra credentials" '
                'field, before injecting.')
        return {'x-trackbox-username': username, 'x-trackbox-password': password}

    # --- transport -------------------------------------------------------------

    def _request(self, method: str, path: str, *, json: dict | None = None, params: dict | None = None):
        """The base request, plus this box's in-body error classification.

        Everything the base does — rate limiting, timeout bounds, HTTP-status
        classification — still applies and runs first; a genuine 500 or a
        read timeout is classified exactly as it is for every other box.
        This only adds the layer the base cannot see, because on TrackBox
        the HTTP status line is not where the answer is.
        """
        parsed = super()._request(method, path, json=json, params=params)
        self._raise_for_soft_error(parsed, path)
        return parsed

    @staticmethod
    def _is_soft_error(parsed) -> bool:
        """Is this body an error despite its 200?

        Tests for an explicitly falsy ``status`` KEY rather than a missing
        one, because their two endpoints differ: the documented successful
        pull response is ``{"data": [...], "meta": {...}}`` with no
        ``status`` key at all, while every error carries ``status: false``.
        Treating "absent" as failure would make every successful pull look
        like an outage.
        """
        return isinstance(parsed, dict) and 'status' in parsed and not parsed['status']

    def _raise_for_soft_error(self, parsed, path: str) -> None:
        """Translate a ``status: false`` body into the shared taxonomy.

        Only raises for outcomes that are NOT a verdict on the lead:

        * auth/permission (AUTH_ERROR_CODES) -> retryable LeadBuyerError.
          Our configuration is wrong; the lead is fine and must survive it.
        * "no room right now" -> LeadBuyerCapacityError, so the lead retries
          on the long schedule or cascades, rather than dying. Same
          reasoning as HypernetConnector.is_capacity_error.

        A lead-level verdict (invalid data, duplicate) is deliberately NOT
        raised here. It is a real answer about this lead, and
        parse_injection_result() renders it as duplicate/failed with the
        buyer's own message attached — which is what puts a readable reason
        on the LeadInjection row instead of a stack trace. Raising would
        also lose the response_payload the operator needs.

        The PULL path has no such caller, so _pull_window() checks
        _is_soft_error() itself — an unhandled error body there must never
        be mistaken for "this window has no rows".
        """
        if not self._is_soft_error(parsed):
            return

        message = str(parsed.get('message') or '')
        try:
            code = int(parsed.get('code') or 0)
        except (TypeError, ValueError):
            code = 0

        if code in self.AUTH_ERROR_CODES:
            # Loud, and deliberately not a lead-level failure: every lead
            # this buyer is handed will fail identically until a human fixes
            # the credentials, so this must read as an outage, not as a
            # string of coincidentally bad leads.
            logger.error(
                'TrackBox buyer %s rejected our CREDENTIALS (code %s) on %s: %s — '
                'no lead sent to this buyer can succeed until this is fixed.',
                self.buyer.slug, code, path, message)
            raise LeadBuyerError(
                f'{path}: TrackBox authentication failed (code {code}): {message}',
                status_code=code)

        if self.CAPACITY_ERROR_PATTERN.search(message):
            raise LeadBuyerCapacityError(
                f'{path}: TrackBox has no capacity right now: {message}', status_code=code)

    # --- payload ----------------------------------------------------------------

    def build_payload(self, lead) -> dict:
        """Their flat signup body: the base's mapped output, plus this box's
        static constants (ai/ci/gi/so/lg), plus the lead attributes the base
        cannot reach.

        Flat, unlike Hypernet — TrackBox takes every field at the top level,
        so no _set_path() is involved.

        The password is REDACTED here, deliberately, and substituted onto
        the wire only in inject_lead(). This method's result is what
        leadgen.tasks.inject_lead_task records as
        LeadInjection.request_payload; an audit trail needs to show what was
        sent, and a redaction marker shows exactly that. See
        BrokerPasswordMixin.

        Precedence matches HypernetConnector: a mapped LEAD value always
        wins over a static constant of the same name, so a box-level default
        can never overwrite what we actually know about this specific lead.
        """
        payload = dict(getattr(self.buyer, 'extra_payload_fields', None) or {})

        for key, value in super().build_payload(lead).items():
            if key in self.PHONE_KEYS:
                value, ambiguous = _normalize_msisdn(value)
                if ambiguous:
                    # Deliberately not raised: inject_lead_task calls
                    # build_payload() OUTSIDE its try block, so an exception
                    # here escapes the task unhandled — no LeadInjection
                    # update, no failure_reason, nothing an operator can
                    # read. Warn and send; the fix belongs at intake.
                    logger.warning(
                        'TrackBox payload for lead #%s carries a national-format phone number '
                        '(no country code) — buyer will likely reject or misdial it.', lead.pk)
            payload[key] = value

        # Their documented `userip`. Outside MAPPABLE_LEAD_FIELDS, like
        # Hypernet's `ip` — adding it there would change what we send to the
        # live op-brandy box.
        if getattr(lead, 'ip', None):
            payload['userip'] = str(lead.ip)

        payload['password'] = self.REDACTED_PASSWORD
        return payload

    def inject_lead(self, lead) -> dict:
        """POST one lead, substituting the real password into the wire body.

        This is the ONLY place the plaintext password exists —
        build_payload() (and therefore the audit trail, and therefore the
        console) sees the redaction marker instead. Overridden rather than
        folded into build_payload() precisely so that separation is
        structural rather than a convention someone has to remember.
        """
        payload = self.build_payload(lead)
        payload['password'] = self.get_or_create_password(lead)
        return self._request('POST', self.box_type.single_endpoint_path, json=payload)

    def inject_batch(self, leads):
        """TrackBox documents no batch endpoint. The base class would happily
        POST ``{"leads": [...]}`` to whatever batch path a BoxType had
        configured, so refuse explicitly rather than relying on
        ``batch_max_size=1`` staying set."""
        raise LeadBuyerError('TrackBox has no batch injection endpoint; inject leads one at a time.')

    # --- response parsing ---------------------------------------------------------

    def _resolve_scope(self, response, path):
        """Walk ``path`` into ``response``, or None if it does not lead to a
        dict. A single-element list is unwrapped, since these boxes return
        one-item collections where a bare object would do."""
        node = response
        for part in path:
            if isinstance(node, list) and len(node) == 1:
                node = node[0]
            if not isinstance(node, dict):
                return None
            node = node.get(part)
        if isinstance(node, list) and len(node) == 1:
            node = node[0]
        return node if isinstance(node, dict) else None

    def _extract_external_id(self, response) -> str:
        """The first present, non-empty id in EXTERNAL_ID_KEYS, searched
        through every scope in RESPONSE_ID_SCOPES in order.

        Searching several scopes rather than one is not defensive padding.
        The live box puts the id at ``addonData.data`` and NOWHERE else on a
        successful signup — a search of the top level and ``data`` alone
        came back empty on the first real delivery.

        Returns '' when nothing matches, having logged the keys that WERE
        present at every scope. That log is the point: an empty external_id
        silently excludes the lead from every future status sync, so a
        delivery should hand an operator the exact key name to add rather
        than leaving them to discover a missing deposit weeks later.
        """
        if not isinstance(response, dict):
            return ''

        searched = []
        for path in self.RESPONSE_ID_SCOPES:
            scope = self._resolve_scope(response, path)
            if scope is None:
                continue
            searched.append((path, scope))
            for key in self.EXTERNAL_ID_KEYS:
                value = scope.get(key)
                if value not in (None, '', []):
                    return str(value)

        logger.error(
            'TrackBox buyer %s returned a success with no recognisable lead id. Searched %s. '
            'Add the right key to TrackBoxConnector.EXTERNAL_ID_KEYS (or the right scope to '
            'RESPONSE_ID_SCOPES) — until then this lead cannot receive status or deposit '
            'updates.',
            self.buyer.slug,
            {'.'.join(path) or '<top level>': sorted(scope) for path, scope in searched})
        return ''

    def sanitize_response_for_audit(self, response):
        """Default-deny filtering, with this box's SCALAR credentials
        neutralised structurally first.

        The allowlist can only express "recurse into this key". That is safe
        for a container and actively harmful for a scalar: a successful
        signup returns ``data`` as the autologin URL itself, and allowlisting
        it published that URL verbatim to response_payload — which is
        rendered to affiliates. Redacting by VALUE SHAPE rather than by name
        means a key that is a credential today and an object tomorrow is
        handled correctly either way, and vice versa.

        Non-dict responses fall straight through to the base class.
        """
        if isinstance(response, dict):
            replaced = {}
            for key, value in response.items():
                if key in self.SCALAR_CREDENTIAL_KEYS and not isinstance(value, (dict, list)):
                    replaced[key] = REDACTED
                else:
                    replaced[key] = value
            response = replaced
        return super().sanitize_response_for_audit(response)

    def parse_injection_result(self, response: dict) -> tuple[str, str, str]:
        """``{"status": ..., "data": {...}, "message": ...}`` -> our
        (external_id, status, failure_reason).

        Reached only for outcomes _raise_for_soft_error() left alone: a
        success, or a verdict on this lead. Auth failures and capacity
        refusals raised before getting here.

        Note what is NOT returned: anything from ``data`` other than the id.
        That object carries autologin URLs — see AUDIT_RESPONSE_ALLOWLIST.
        """
        if not isinstance(response, dict) or not response:
            # _request() returns {} for a 2xx with an empty body. This box
            # always answers with a JSON envelope, so an empty body is
            # unexplained — not a success.
            return '', 'failed', 'Empty response body from TrackBox (expected a JSON result).'

        if response.get('status'):
            return self._extract_external_id(response), 'delivered', ''

        message = str(response.get('message') or response.get('error') or '')
        code = response.get('code')
        detail = f'[{code}] {message}' if code else (message or str(response))
        status = 'duplicate' if self.DUPLICATE_PATTERN.search(message) else 'failed'
        return '', status, detail[:255]

    # --- status sync ----------------------------------------------------------------

    def _row_id(self, row) -> str:
        """The external id on one pull row — a candidate set, for the same
        reason EXTERNAL_ID_KEYS is one."""
        if not isinstance(row, dict):
            return ''
        for key in self.ROW_ID_KEYS:
            value = row.get(key)
            if value not in (None, '', []):
                return str(value)
        return ''

    @staticmethod
    def _window_param(dt) -> str:
        """Their documented wire format: ``YYYY-MM-DD HH:MM:SS``, no timezone
        marker. Sent as UTC, matching how the windows are built."""
        return dt.astimezone(dt_timezone.utc).strftime('%Y-%m-%d %H:%M:%S')

    def fetch_leads(self, **filters) -> dict:
        """Their pull endpoint is a POST with a JSON BODY, not the base
        class's GET with a query string — override, or every status sync
        would send its window as query params the box ignores and get an
        unfiltered (or empty) answer back."""
        return self._request('POST', self.box_type.fetch_endpoint_path, json=dict(filters))

    def _pull_window(self, start, end):
        """Every row in [start, end], following their page-number pagination.

        Their ``meta`` carries ``currentPage``/``lastPage``, so this pages
        until the last page is reached rather than until a short page comes
        back. Stops early on an empty page too, so a wrong ``lastPage``
        cannot loop; STATUS_SYNC_MAX_PAGES bounds it either way.

        ``type: "3"`` is Leads + Deposits — we want the status of every
        delivered lead, not only the ones that already deposited. Asking for
        type 4 (deposits only) would make a lead's status invisible until it
        converted, which is precisely the progression the sync exists to
        report.

        An error body here is RAISED rather than read as an empty window:
        this box answers 200 to failures, so a silent `data: []` fallback
        would turn an auth outage into "no leads changed" and the sync would
        log as healthy while reporting nothing. _raise_for_soft_error()
        already handles auth and capacity; this catches everything else.
        """
        collected = []
        page = 1
        for _ in range(self.STATUS_SYNC_MAX_PAGES):
            response = self.fetch_leads(**{
                'from': self._window_param(start),
                'to': self._window_param(end),
                'type': '3',
                'page': str(page),
            })
            if self._is_soft_error(response):
                raise LeadBuyerError(
                    f'TrackBox pull failed for window {start}..{end}: '
                    f'{str(response.get("message") or response)[:200]}')

            rows = (response or {}).get('data') or []
            collected.extend(rows)

            meta = (response or {}).get('meta') or {}
            last_page = meta.get('lastPage')
            if not rows or not isinstance(last_page, int) or page >= last_page:
                return collected
            page += 1

        logger.warning(
            'TrackBox status sync: hit STATUS_SYNC_MAX_PAGES (%s) for window %s..%s on buyer %s; '
            'results may be incomplete.',
            self.STATUS_SYNC_MAX_PAGES, start, end, self.buyer.slug)
        return collected

    def parse_status_sync_results(self, response: dict) -> list[dict]:
        """TrackBox rows -> the shared status-sync contract.

        Every source key here is a CANDIDATE SET, for the reason given in
        the class docstring: their docs publish no row schema. Each getter
        below falls back through the plausible spellings and yields a benign
        empty value rather than inventing one.

        ``deposit`` is the field that bills, so it is read conservatively:
        only an explicitly truthy deposit flag — or a status string that
        says "deposit" — counts. An unrecognised row reports deposit=False
        and its raw status, which leaves the lead visible and unconverted
        rather than falsely converted.

        ``updated_at`` follows Hypernet's compromise: a real timestamp when
        the box gives one, '' otherwise. tasks._parse_buyer_timestamp turns
        '' into None, which reads as "we do not know when" — the honest
        encoding. Stamping sync time instead would assert the status changed
        at the moment we happened to poll, which is false.
        """
        results = []
        for row in (response or {}).get(self.ROWS_KEY) or []:
            if not isinstance(row, dict):
                continue
            external_id = self._row_id(row)
            if not external_id:
                continue

            buyer_status = str(_first_present(
                row, 'status', 'statusName', 'leadStatus', 'saleStatus') or '')
            deposit_flag = _first_present(row, 'deposit', 'isDeposited', 'ftd', 'isFtd')

            results.append({
                'external_id': external_id,
                'buyer_status': buyer_status,
                'deposit': _truthy(deposit_flag) or 'deposit' in buyer_status.lower(),
                'updated_at': str(_first_present(
                    row, 'depositDate', 'depositedAt', 'statusDate', 'updatedAt') or ''),
                'country_iso2': str(_first_present(row, 'country', 'geo', 'countryCode') or '')[:2],
            })
        return results
