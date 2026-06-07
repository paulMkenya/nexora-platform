"""Shared NOWPayments transport — base URL resolution, the money-safety mainnet
guard, JWT auth (cached, with a single 401-refresh-retry) and a sanitized
request helper.

This module is provider-surface-agnostic: the Mass Payouts client
(:mod:`payouts.providers.nowpayments.payouts`) builds on it now, and a future
deposits client (``payments.py``) is expected to reuse the very same base without
modification. Nothing here knows about payouts specifically.

Security posture (deliberate, not incidental):
  * SANDBOX BY DEFAULT. The base URL defaults to the NOWPayments sandbox. If the
    configured base URL looks like the production/mainnet host, the client refuses
    to initialise unless ``NOWPAYMENTS_ALLOW_MAINNET`` is explicitly enabled. This
    is a money-safety guard — a misconfiguration must fail loud, not move real funds.
  * NO SECRETS IN LOGS OR EXCEPTIONS. Auth headers and any request body that could
    carry credentials are never logged, and error messages carry only the status
    code plus a sanitized snippet of the response.
"""
import logging
from typing import Any, Optional
from urllib.parse import urlparse

import requests
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

logger = logging.getLogger(__name__)

# The documented NOWPayments hosts. The sandbox is the only safe default; any host
# that is not clearly the sandbox is treated as production by the mainnet guard.
SANDBOX_HOST = 'api-sandbox.nowpayments.io'
PRODUCTION_HOST = 'api.nowpayments.io'

# Network timeout (seconds) for every NOWPayments call. Kept short so a hung
# provider can never wedge a Celery worker (PR #11 runs these from tasks).
DEFAULT_TIMEOUT = 30


class NowPaymentsError(Exception):
    """A NOWPayments API call returned a non-2xx response or could not be reached.

    Carries the HTTP ``status_code`` (``None`` for transport/connection errors) and
    a ``message`` that is already sanitized — it never contains credentials, auth
    headers or request bodies.
    """

    def __init__(self, message: str, *, status_code: Optional[int] = None):
        self.status_code = status_code
        self.message = message
        super().__init__(message if status_code is None else f'[{status_code}] {message}')


def _looks_like_production(base_url: str) -> bool:
    """True when ``base_url`` points at anything other than the sandbox host.

    Conservative on purpose: an unrecognised/empty host counts as production so a
    typo can't quietly bypass the guard and hit mainnet.
    """
    host = (urlparse(base_url).hostname or '').lower()
    return host != SANDBOX_HOST


class NowPaymentsBaseClient:
    """Shared base for every NOWPayments API surface.

    Subclasses provide the specific endpoints; this class owns base-URL resolution,
    the mainnet guard, JWT acquisition/caching, the 401-refresh-retry and the
    sanitized ``_request`` helper.
    """

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        email: Optional[str] = None,
        password: Optional[str] = None,
        base_url: Optional[str] = None,
        allow_mainnet: Optional[bool] = None,
        timeout: int = DEFAULT_TIMEOUT,
    ):
        """Resolve config (args override settings) and enforce the mainnet guard.

        Credentials default to the sandbox-specific settings so this client can
        never read — or re-arm — the legacy provider's ``NOWPAYMENTS_API_KEY``.
        Tests inject dummy values directly. Raises
        :class:`~django.core.exceptions.ImproperlyConfigured` on a mainnet URL
        without the explicit opt-in.
        """
        self._api_key = (
            api_key if api_key is not None
            else getattr(settings, 'NOWPAYMENTS_SANDBOX_API_KEY', '')
        )
        self._email = (
            email if email is not None
            else getattr(settings, 'NOWPAYMENTS_SANDBOX_EMAIL', '')
        )
        self._password = (
            password if password is not None
            else getattr(settings, 'NOWPAYMENTS_SANDBOX_PASSWORD', '')
        )
        base_url = (
            base_url if base_url is not None
            else getattr(settings, 'NOWPAYMENTS_BASE_URL', f'https://{SANDBOX_HOST}/v1')
        )
        allow_mainnet = (
            allow_mainnet if allow_mainnet is not None
            else getattr(settings, 'NOWPAYMENTS_ALLOW_MAINNET', False)
        )

        if not base_url:
            raise ImproperlyConfigured('NOWPAYMENTS_BASE_URL is empty.')

        # --- money-safety guard ------------------------------------------------
        if _looks_like_production(base_url) and not allow_mainnet:
            raise ImproperlyConfigured(
                'NOWPayments base URL is not the sandbox host '
                f'({SANDBOX_HOST}) and NOWPAYMENTS_ALLOW_MAINNET is not set. '
                'Refusing to initialise against a production-looking endpoint. '
                'Set NOWPAYMENTS_BASE_URL to the sandbox, or explicitly set '
                'NOWPAYMENTS_ALLOW_MAINNET=true to target mainnet on purpose.'
            )

        self.base_url = base_url.rstrip('/')
        self.timeout = timeout
        self._jwt: Optional[str] = None  # cached in-memory for this instance only

    # --- auth ------------------------------------------------------------------

    def _get_jwt(self, *, force_refresh: bool = False) -> str:
        """Return a JWT, fetching (and caching on the instance) on first use.

        ``force_refresh`` discards any cached token and re-authenticates — used by
        the 401-retry path. Never logs the email, password or the token itself.
        """
        if self._jwt and not force_refresh:
            return self._jwt

        if not self._email or not self._password:
            raise NowPaymentsError(
                'Cannot authenticate: NOWPAYMENTS_SANDBOX_EMAIL / '
                'NOWPAYMENTS_SANDBOX_PASSWORD are not configured.'
            )

        try:
            resp = requests.post(
                f'{self.base_url}/auth',
                json={'email': self._email, 'password': self._password},
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise NowPaymentsError(f'auth request failed: {exc.__class__.__name__}') from exc

        if not resp.ok:
            raise NowPaymentsError(
                f'auth failed: {_sanitize_body(resp)}', status_code=resp.status_code)

        token = (resp.json() or {}).get('token', '')
        if not token:
            raise NowPaymentsError('auth response did not contain a token.',
                                   status_code=resp.status_code)
        self._jwt = token
        logger.info('NOWPayments JWT acquired (token length=%d).', len(token))
        return token

    # --- transport -------------------------------------------------------------

    def _request(
        self,
        method: str,
        path: str,
        *,
        auth: str = 'jwt',
        json: Optional[dict] = None,
        params: Optional[dict] = None,
    ) -> Any:
        """Perform a request, attach the right headers, and parse JSON.

        ``auth`` selects the credential scheme:
          * ``'jwt'``     — ``Authorization: Bearer <token>`` (most endpoints).
          * ``'api-key'`` — ``x-api-key`` only (e.g. /status).
          * ``'both'``    — both headers (e.g. POST /payout).
          * ``'none'``    — no auth headers.

        On a 401 for a JWT-bearing request the token is refreshed once and the call
        retried a single time. Auth headers and request bodies are never logged;
        errors raise :class:`NowPaymentsError` with a sanitized message.
        """
        url = f'{self.base_url}/{path.lstrip("/")}'
        try:
            resp = self._send(method, url, auth=auth, json=json, params=params)
            if resp.status_code == 401 and auth in ('jwt', 'both'):
                logger.info('NOWPayments 401 on %s — refreshing JWT and retrying once.', path)
                resp = self._send(method, url, auth=auth, json=json, params=params,
                                  force_refresh=True)
        except requests.RequestException as exc:
            # Never interpolate the exception's repr blindly — class name only.
            raise NowPaymentsError(
                f'request to {path} failed: {exc.__class__.__name__}') from exc

        if not resp.ok:
            raise NowPaymentsError(
                f'{method} {path} -> {_sanitize_body(resp)}', status_code=resp.status_code)
        if not resp.content:
            return {}
        try:
            return resp.json()
        except ValueError as exc:
            raise NowPaymentsError(
                f'{method} {path} returned non-JSON body.',
                status_code=resp.status_code) from exc

    def _send(self, method, url, *, auth, json, params, force_refresh=False):
        """Build headers (with the selected auth scheme) and fire the request."""
        headers = {'Content-Type': 'application/json'}
        if auth in ('api-key', 'both'):
            headers['x-api-key'] = self._api_key
        if auth in ('jwt', 'both'):
            headers['Authorization'] = f'Bearer {self._get_jwt(force_refresh=force_refresh)}'
        return requests.request(
            method, url, headers=headers, json=json, params=params, timeout=self.timeout)


def _sanitize_body(resp: requests.Response) -> str:
    """A short, safe snippet of a response body for error messages.

    We only ever surface response bodies (NOWPayments error payloads), never
    request bodies — so credentials we send are never echoed back into an
    exception. Truncated to keep logs/messages bounded.
    """
    try:
        text = resp.text or ''
    except Exception:  # noqa: BLE001 — never let logging/error-building raise
        return '<unreadable response body>'
    text = text.replace('\n', ' ').strip()
    return text[:200] if text else '<empty response body>'
