"""
NOWPayments payout API provider.
Env vars: NOWPAYMENTS_API_KEY, NOWPAYMENTS_IPN_SECRET (blank = disabled).
"""
import hashlib
import hmac
import logging
import os
from typing import Optional

import requests as _requests

from .base import CryptoPayoutProvider, CryptoPayoutResult
from .validators import validate_address

logger = logging.getLogger(__name__)

_API_BASE = 'https://api.nowpayments.io/v1'


class NowPaymentsProvider(CryptoPayoutProvider):
    def __init__(self):
        self._api_key = os.environ.get('NOWPAYMENTS_API_KEY', '').strip()
        self._ipn_secret = os.environ.get('NOWPAYMENTS_IPN_SECRET', '').strip()

    def is_enabled(self) -> bool:
        return bool(self._api_key)

    def validate_address(self, network: str, address: str) -> bool:
        return validate_address(network, address)

    def estimate_fee(self, network: str, amount_usd: float) -> Optional[str]:
        if not self.is_enabled():
            return None
        try:
            currency = _network_to_currency(network)
            resp = _requests.get(
                f'{_API_BASE}/estimate',
                params={'amount': amount_usd, 'currency_from': 'usd', 'currency_to': currency},
                headers={'x-api-key': self._api_key},
                timeout=10,
            )
            data = resp.json()
            estimated = data.get('estimated_amount', '')
            return f'~{estimated} {currency.upper()}' if estimated else None
        except Exception as exc:
            logger.warning('nowpayments fee estimate failed: %s', exc)
            return None

    def send_payout(
        self,
        network: str,
        wallet_address: str,
        amount_usd: float,
        payout_request_id: int,
    ) -> CryptoPayoutResult:
        if not self.is_enabled():
            return CryptoPayoutResult(success=False, error='NOWPayments disabled')
        if not self.validate_address(network, wallet_address):
            return CryptoPayoutResult(success=False, error=f'Invalid address for {network}')
        currency = _network_to_currency(network)
        try:
            resp = _requests.post(
                f'{_API_BASE}/payout',
                json={
                    'withdrawals': [{
                        'address': wallet_address,
                        'currency': currency,
                        'amount': amount_usd,
                        'ipn_callback_url': _ipn_url(),
                        'extra_id': str(payout_request_id),
                    }]
                },
                headers={'x-api-key': self._api_key, 'Content-Type': 'application/json'},
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            withdrawals = data.get('withdrawals', [])
            if withdrawals:
                w = withdrawals[0]
                tx_hash = w.get('hash', '') or w.get('id', '')
                return CryptoPayoutResult(success=True, tx_hash=str(tx_hash))
            return CryptoPayoutResult(success=False, error=f'Unexpected response: {data}')
        except _requests.HTTPError as exc:
            msg = f'HTTP {exc.response.status_code}: {exc.response.text[:200]}'
            return CryptoPayoutResult(success=False, error=msg)
        except Exception as exc:
            return CryptoPayoutResult(success=False, error=str(exc))

    def get_status(self, tx_hash: str, network: str) -> str:
        if not tx_hash or not self.is_enabled():
            return 'pending'
        try:
            resp = _requests.get(
                f'{_API_BASE}/payment/{tx_hash}',
                headers={'x-api-key': self._api_key},
                timeout=10,
            )
            data = resp.json()
            status = data.get('payment_status', '')
            if status in ('finished', 'confirmed'):
                return 'confirmed'
            if status in ('failed', 'refunded', 'expired'):
                return 'failed'
            return 'pending'
        except Exception:
            return 'pending'

    def verify_ipn(self, payload: bytes, sig_header: str) -> bool:
        if not self._ipn_secret:
            return False
        expected = hmac.new(self._ipn_secret.encode(), payload, hashlib.sha512).hexdigest()
        return hmac.compare_digest(sig_header, expected)


def _network_to_currency(network: str) -> str:
    mapping = {
        'USDT-TRC20': 'usdttrc20',
        'USDT-Polygon': 'usdtmatic',
        'USDC-Polygon': 'usdcmatic',
        'USDC-Base': 'usdcbase',
        'USDC-ERC20': 'usdc',
        'ETH': 'eth',
        'BTC': 'btc',
    }
    return mapping.get(network, network.lower())


def _ipn_url() -> str:
    from django.conf import settings
    base = getattr(settings, 'TRACKER_URL', '')
    return f'{base}/webhooks/nowpayments/' if base else ''
