"""Generic, config-driven connector for outbound lead delivery.

Handles the common REST + query-string-or-header API key + JSON single/batch
leads shape used by most lead-buyer platforms — op-brandy.com, the first
configured buyer, is exactly this shape. A NEW buyer that follows the same
shape needs ONLY a new LeadBuyer config row, no code. A buyer with a
meaningfully different API (a different auth scheme entirely, XML, SOAP)
should subclass this and override _request()/build_payload().

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
from urllib.parse import urljoin

import requests

from .ratelimit import TokenBucket

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 15


class LeadBuyerError(Exception):
    """A buyer API call returned a non-2xx response or could not be reached.

    Carries the HTTP ``status_code`` (``None`` for transport/connection
    errors) and a ``message`` that is already sanitized.
    """

    def __init__(self, message: str, *, status_code: int | None = None):
        self.status_code = status_code
        self.message = message
        super().__init__(message if status_code is None else f'[{status_code}] {message}')


def _sanitize_body(resp) -> str:
    try:
        text = resp.text or ''
    except Exception:  # noqa: BLE001 — never let logging/error-building raise
        return '<unreadable response body>'
    text = text.replace('\n', ' ').strip()
    return text[:300] if text else '<empty response body>'


class LeadBuyerConnector:
    """Connector for one configured LeadBuyer, fully config-driven."""

    def __init__(self, buyer, *, timeout: int = DEFAULT_TIMEOUT):
        self.buyer = buyer
        self.timeout = timeout
        self._bucket = TokenBucket.for_buyer(buyer)

    # --- payload mapping -----------------------------------------------------

    def _map_field(self, our_name: str) -> str:
        return self.buyer.field_mapping.get(our_name, our_name)

    def build_payload(self, lead) -> dict:
        """Map a leadgen.Lead onto the buyer's own field names. ``deposit``
        is deliberately NOT sent here — a lead has no deposit at submission
        time; deposit status flows the other way, via
        leadgen.tasks.sync_buyer_statuses (see fetch_lead_statuses() below)."""
        values = {
            'firstname': lead.first_name,
            'lastname': lead.last_name,
            'email': lead.email,
            'phone': lead.phone,
            'vertical': lead.vertical,
            'source_id': lead.source_id or str(lead.pk),
        }
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

        if self.buyer.auth_type == self.buyer.AUTH_API_KEY_QUERY:
            params[self.buyer.auth_param_name] = api_key
        elif self.buyer.auth_type == self.buyer.AUTH_API_KEY_HEADER:
            headers[self.buyer.auth_param_name] = api_key
        elif self.buyer.auth_type == self.buyer.AUTH_BEARER:
            headers['Authorization'] = f'Bearer {api_key}'

        self._bucket.acquire()
        try:
            resp = requests.request(
                method, url, headers=headers, params=params, json=json, timeout=self.timeout)
        except requests.RequestException as exc:
            raise LeadBuyerError(f'request to {path} failed: {exc.__class__.__name__}') from exc

        if not resp.ok:
            raise LeadBuyerError(f'{method} {path} -> {_sanitize_body(resp)}', status_code=resp.status_code)
        if not resp.content:
            return {}
        try:
            return resp.json()
        except ValueError as exc:
            raise LeadBuyerError(
                f'{method} {path} returned non-JSON body.', status_code=resp.status_code) from exc

    # --- public API --------------------------------------------------------------

    def inject_lead(self, lead) -> dict:
        """POST one lead. Returns the buyer's parsed response dict.
        Raises LeadBuyerError on transport/HTTP failure — the Celery task
        (tasks.py) translates that into a LeadInjection row."""
        payload = self.build_payload(lead)
        return self._request('POST', self.buyer.single_endpoint_path, json=payload)

    def inject_batch(self, leads) -> dict:
        """POST a batch. Returns the buyer's parsed response dict — the
        added/failed split is buyer-specific, callers inspect the raw
        response (see tasks.inject_batch_task)."""
        if not self.buyer.supports_batch:
            raise LeadBuyerError(f'{self.buyer.name} does not support batch injection')
        payload = {'leads': [self.build_payload(lead) for lead in leads]}
        return self._request('POST', self.buyer.batch_endpoint_path, json=payload)

    def fetch_leads(self, **filters) -> dict:
        return self._request('GET', self.buyer.fetch_endpoint_path, params=filters)

    # --- response parsing --------------------------------------------------------

    def parse_injection_result(self, response: dict) -> tuple[str, str, str]:
        """(external_id, status, failure_reason) from a single-lead inject
        response. Default assumes op-brandy's envelope — both its single and
        batch endpoints return {"addedLeads": [...], "failedToAddLeads": [...]}
        — which is common enough across this class of API to be the sane
        default; a buyer with a different envelope overrides this one method.
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
        status.updatedAtUtc / countryIso2) — override for a buyer with a
        different GET /leads shape. ``country_iso2`` is a free byproduct of
        this same call (the buyer derives it from the phone number on their
        side) — a zero-cost backfill for Lead.country_iso2 alongside
        IPSTACK-based geolocation at intake (see tasks.geolocate_lead)."""
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
