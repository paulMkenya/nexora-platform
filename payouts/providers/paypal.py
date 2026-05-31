"""PayPal Payouts API — env PAYPAL_CLIENT_ID, PAYPAL_CLIENT_SECRET (blank=disabled)."""
import logging
import os

import requests as _requests

logger = logging.getLogger(__name__)


class PayPalProvider:
    def __init__(self):
        self._client_id = os.environ.get('PAYPAL_CLIENT_ID', '').strip()
        self._client_secret = os.environ.get('PAYPAL_CLIENT_SECRET', '').strip()
        env = os.environ.get('PAYPAL_ENVIRONMENT', 'sandbox').strip()
        self._base = (
            'https://api-m.paypal.com'
            if env == 'production'
            else 'https://api-m.sandbox.paypal.com'
        )

    def is_enabled(self) -> bool:
        return bool(self._client_id and self._client_secret)

    def send_payout(self, payout_request, pm) -> bool:
        from payouts.models import STATUS_PROCESSING, STATUS_FAILED
        details = pm.details if pm else {}
        email = details.get('email', '')
        if not email:
            payout_request.status = STATUS_FAILED
            payout_request.notes = 'Missing PayPal email'
            return False
        try:
            token = self._get_token()
            batch_id = self._create_payout(token, email, float(payout_request.amount), payout_request.pk)
            payout_request.status = STATUS_PROCESSING
            payout_request.tx_ref = batch_id
            return True
        except Exception as exc:
            logger.error('PayPal payout error req=%s: %s', payout_request.pk, exc)
            payout_request.status = STATUS_FAILED
            payout_request.notes = str(exc)
            return False

    def _get_token(self) -> str:
        resp = _requests.post(
            f'{self._base}/v1/oauth2/token',
            data='grant_type=client_credentials',
            auth=(self._client_id, self._client_secret),
            headers={'Content-Type': 'application/x-www-form-urlencoded'},
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()['access_token']

    def _create_payout(self, token: str, email: str, amount: float, request_id: int) -> str:
        import uuid
        resp = _requests.post(
            f'{self._base}/v1/payments/payouts',
            json={
                'sender_batch_header': {
                    'sender_batch_id': f'nexora-{request_id}-{uuid.uuid4().hex[:8]}',
                    'email_subject': 'Nexora Affiliate Payout',
                },
                'items': [{
                    'recipient_type': 'EMAIL',
                    'amount': {'value': f'{amount:.2f}', 'currency': 'USD'},
                    'receiver': email,
                    'note': f'Nexora affiliate payout #{request_id}',
                    'sender_item_id': str(request_id),
                }],
            },
            headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json().get('batch_header', {}).get('payout_batch_id', '')
