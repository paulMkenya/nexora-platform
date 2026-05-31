"""Wise (formerly TransferWise) payout provider — env WISE_API_KEY (blank=disabled)."""
import logging
import os

import requests as _requests

logger = logging.getLogger(__name__)
_API_BASE = 'https://api.wise.com/v3'


class WiseProvider:
    def __init__(self):
        self._api_key = os.environ.get('WISE_API_KEY', '').strip()
        self._profile_id = os.environ.get('WISE_PROFILE_ID', '').strip()

    def is_enabled(self) -> bool:
        return bool(self._api_key and self._profile_id)

    def send_payout(self, payout_request, pm) -> bool:
        from payouts.models import STATUS_PROCESSING, STATUS_FAILED
        details = pm.details if pm else {}
        try:
            quote = self._create_quote(float(payout_request.amount), payout_request.currency)
            transfer = self._create_transfer(quote['id'], details)
            self._fund_transfer(transfer['id'])
            payout_request.status = STATUS_PROCESSING
            payout_request.tx_ref = str(transfer['id'])
            return True
        except Exception as exc:
            logger.error('Wise payout error req=%s: %s', payout_request.pk, exc)
            payout_request.status = STATUS_FAILED
            payout_request.notes = str(exc)
            return False

    def _headers(self):
        return {'Authorization': f'Bearer {self._api_key}', 'Content-Type': 'application/json'}

    def _create_quote(self, amount: float, currency: str) -> dict:
        resp = _requests.post(
            f'{_API_BASE}/quotes',
            json={
                'sourceCurrency': 'USD',
                'targetCurrency': currency.upper(),
                'sourceAmount': amount,
                'profile': int(self._profile_id),
            },
            headers=self._headers(),
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    def _create_transfer(self, quote_id: str, details: dict) -> dict:
        resp = _requests.post(
            f'{_API_BASE}/transfers',
            json={
                'targetAccount': details.get('recipient_id', ''),
                'quoteUuid': quote_id,
                'customerTransactionId': details.get('ref', ''),
                'details': {'reference': 'Nexora payout'},
            },
            headers=self._headers(),
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    def _fund_transfer(self, transfer_id: str):
        resp = _requests.post(
            f'{_API_BASE}/transfers/{transfer_id}/payments',
            json={'type': 'BALANCE'},
            headers=self._headers(),
            timeout=30,
        )
        resp.raise_for_status()
