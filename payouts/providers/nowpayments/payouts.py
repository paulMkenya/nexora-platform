"""NOWPayments Mass Payouts client.

One affiliate payout maps to exactly one batch with a single withdrawal entry
(single-withdrawal-per-batch model). All transport, auth and the mainnet guard
live in :mod:`payouts.providers.nowpayments.base`; this module only knows the
payout endpoints.

Money handling: amounts are :class:`~decimal.Decimal` internally and are only
rendered to ``<=6`` decimal-place strings at the API boundary.

PR #11 wires this client beneath the withdrawal control layer (see
``payouts.providers.dispatch._dispatch_crypto``). It stays INERT until an operator
sets both gates live (``CRYPTO_DISPATCH_ENABLED`` and ``NOWPAYMENTS_ALLOW_MAINNET``);
the base URL defaults to the sandbox host so the mainnet guard stays armed.
"""
import logging
from decimal import ROUND_DOWN, Decimal
from typing import Any, Optional

import pyotp
from django.conf import settings

from .base import NowPaymentsBaseClient, NowPaymentsError

logger = logging.getLogger(__name__)

# NOWPayments rejects amounts with more than 6 decimal places.
_AMOUNT_QUANTUM = Decimal('0.000001')

# Affiliate payout-method ``network`` labels mapped to NOWPayments currency codes.
# An unknown network falls through to its lowercased form (callers may instead
# fall back to NOWPAYMENTS_DEFAULT_CURRENCY when no network is set).
_NETWORK_TO_CURRENCY = {
    'USDT-TRC20': 'usdttrc20',
    'USDT-Polygon': 'usdtmatic',
    'USDC-Polygon': 'usdcmatic',
    'USDC-Base': 'usdcbase',
    'USDC-ERC20': 'usdc',
    'ETH': 'eth',
    'BTC': 'btc',
}


def network_to_currency(network: str) -> str:
    """Map an affiliate payout-method ``network`` label to a NOWPayments currency."""
    return _NETWORK_TO_CURRENCY.get(network, (network or '').lower())


def format_amount(amount) -> str:
    """Render ``amount`` as a string with at most 6 decimal places.

    Accepts a Decimal/str/int; truncates (never rounds up — we must not pay out
    more than requested) to 6 dp and strips trailing zeros while keeping a bare
    integer intact (e.g. ``"10"``, ``"10.5"``, ``"0.123456"``).
    """
    d = amount if isinstance(amount, Decimal) else Decimal(str(amount))
    if d < 0:
        raise ValueError('payout amount cannot be negative')
    d = d.quantize(_AMOUNT_QUANTUM, rounding=ROUND_DOWN)
    # Normalize removes trailing zeros but can yield exponent form for integers
    # (e.g. Decimal('10') -> '1E+1'); guard against that.
    normalized = d.normalize()
    if normalized == normalized.to_integral():
        return str(normalized.quantize(Decimal('1')))
    return format(normalized, 'f')


class NowPaymentsPayoutClient(NowPaymentsBaseClient):
    """Client for the NOWPayments Mass Payouts API (sandbox base URL by default).

    Auth/transport/mainnet-guard concerns are inherited from
    :class:`~payouts.providers.nowpayments.base.NowPaymentsBaseClient`.
    """

    def __init__(self, *, totp_secret: Optional[str] = None,
                 ipn_callback_url: Optional[str] = None, **kwargs):
        """Initialise the payout client.

        ``totp_secret`` / ``ipn_callback_url`` default to the ``NOWPAYMENTS_*``
        settings; the rest of the config (creds, base URL, mainnet guard) is
        resolved by the base class. Raises ``ImproperlyConfigured`` on a mainnet
        URL without the explicit opt-in.
        """
        super().__init__(**kwargs)
        self._totp_secret = (
            totp_secret if totp_secret is not None
            else getattr(settings, 'NOWPAYMENTS_TOTP_SECRET', '')
        )
        self._ipn_callback_url = (
            ipn_callback_url if ipn_callback_url is not None
            else getattr(settings, 'NOWPAYMENTS_IPN_CALLBACK_URL', '')
        )

    def is_enabled(self) -> bool:
        """True when an API key is configured. Mirrors the other crypto providers'
        feature-flag check used by the dispatch layer and the fee-estimate view.

        Note this is a credential check only — it is NOT the dispatch kill-switch.
        ``CRYPTO_DISPATCH_ENABLED`` (checked first in ``_dispatch_crypto``) is the
        gate that actually permits a real send.
        """
        return bool(self._api_key)

    # --- read-only / preflight -------------------------------------------------

    def estimate_fee(self, network: str, amount_usd) -> Optional[str]:
        """GET /estimate (api-key). Best-effort human-readable payout estimate.

        Returns a string like ``"~12.34 USDTTRC20"`` or ``None`` if the estimate
        is unavailable. Never raises — the fee preview is non-critical; any
        provider/transport error degrades to ``None``.
        """
        currency = network_to_currency(network)
        try:
            data = self._request(
                'GET', '/estimate', auth='api-key',
                params={'amount': amount_usd, 'currency_from': 'usd',
                        'currency_to': currency})
        except NowPaymentsError as exc:
            logger.warning('nowpayments fee estimate failed: %s', exc)
            return None
        estimated = (data or {}).get('estimated_amount', '')
        return f'~{estimated} {currency.upper()}' if estimated else None

    def get_status(self) -> dict:
        """GET /status (api-key). Raw API status dict. Used by preflight."""
        return self._request('GET', '/status', auth='api-key')

    def get_balance(self) -> dict:
        """GET /balance (JWT). Custody balances. Preflight + later funding checks."""
        return self._request('GET', '/balance', auth='jwt')

    def validate_address(self, address: str, currency: str,
                         extra_id: Optional[str] = None) -> bool:
        """POST /payout/validate-address (JWT).

        Returns ``True`` when NOWPayments accepts the address for ``currency``.
        A non-2xx raises :class:`NowPaymentsError`; callers that want to use this
        purely as an endpoint-existence probe (preflight) should catch that.
        """
        payload: dict[str, Any] = {'address': address, 'currency': currency}
        if extra_id:
            payload['extra_id'] = extra_id
        # A 2xx means the address validated. (NOWPayments returns an empty/ok body.)
        self._request('POST', '/payout/validate-address', auth='jwt', json=payload)
        return True

    # --- mutating --------------------------------------------------------------

    def create_payout(self, address: str, currency: str, amount,
                      extra_id: Optional[str] = None) -> dict:
        """POST /payout (JWT + api-key). Create a one-entry batch. Does NOT verify.

        Builds a ``withdrawals`` array with EXACTLY ONE entry, formats ``amount``
        to a ``<=6`` dp string, and includes our ``ipn_callback_url``. Returns the
        parsed response (carrying the batch id and the withdrawal id). The batch is
        unverified until :meth:`verify_payout` is called.
        """
        withdrawal: dict[str, Any] = {
            'address': address,
            'currency': currency,
            'amount': format_amount(amount),
        }
        if extra_id:
            withdrawal['extra_id'] = extra_id
        if self._ipn_callback_url:
            withdrawal['ipn_callback_url'] = self._ipn_callback_url
        return self._request('POST', '/payout', auth='both',
                             json={'withdrawals': [withdrawal]})

    def verify_payout(self, batch_id) -> dict:
        """POST /payout/{batch_id}/verify (JWT) with a freshly generated TOTP code.

        Generates a 2FA code from ``NOWPAYMENTS_TOTP_SECRET`` via pyotp and
        submits it to confirm the batch.

        WARNING: NOWPayments permanently locks a batch after 10 failed verify
        attempts — a stuck batch cannot be recovered. The caller must NOT blindly
        retry this; treat a failure as terminal and surface it for human review.
        """
        if not self._totp_secret:
            raise NowPaymentsError(
                'Cannot verify payout: NOWPAYMENTS_TOTP_SECRET is not configured.')
        code = pyotp.TOTP(self._totp_secret).now()
        return self._request('POST', f'/payout/{batch_id}/verify', auth='jwt',
                             json={'verification_code': code})

    def get_payout_status(self, batch_id) -> dict:
        """GET /payout/{batch_id} (JWT). Parsed batch status."""
        return self._request('GET', f'/payout/{batch_id}', auth='jwt')
