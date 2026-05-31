"""
Safaricom M-Pesa Daraja B2C payout provider.
Env vars: MPESA_CONSUMER_KEY, MPESA_CONSUMER_SECRET, MPESA_B2C_SHORTCODE,
          MPESA_B2C_INITIATOR, MPESA_B2C_CREDENTIAL, MPESA_ENVIRONMENT (sandbox|production).
All blank = disabled.
Callback: /webhooks/mpesa/b2c/
"""
import base64
import logging
import os

import requests as _requests

logger = logging.getLogger(__name__)


class MpesaProvider:
    def __init__(self):
        self._key = os.environ.get('MPESA_CONSUMER_KEY', '').strip()
        self._secret = os.environ.get('MPESA_CONSUMER_SECRET', '').strip()
        self._shortcode = os.environ.get('MPESA_B2C_SHORTCODE', '').strip()
        self._initiator = os.environ.get('MPESA_B2C_INITIATOR', '').strip()
        self._credential = os.environ.get('MPESA_B2C_CREDENTIAL', '').strip()
        env = os.environ.get('MPESA_ENVIRONMENT', 'sandbox').strip()
        self._base = (
            'https://api.safaricom.co.ke'
            if env == 'production'
            else 'https://sandbox.safaricom.co.ke'
        )

    def is_enabled(self) -> bool:
        return bool(self._key and self._secret and self._shortcode)

    def send_payout(self, payout_request, pm) -> bool:
        from payouts.models import STATUS_PROCESSING, STATUS_FAILED
        details = pm.details if pm else {}
        phone = details.get('phone', '')
        if not phone:
            payout_request.status = STATUS_FAILED
            payout_request.notes = 'Missing phone number'
            return False
        try:
            token = self._get_token()
            result = self._b2c_payment(token, phone, float(payout_request.amount), payout_request.pk)
            payout_request.status = STATUS_PROCESSING
            payout_request.tx_ref = result.get('ConversationID', '')
            return True
        except Exception as exc:
            logger.error('M-Pesa payout error req=%s: %s', payout_request.pk, exc)
            payout_request.status = STATUS_FAILED
            payout_request.notes = str(exc)
            return False

    def _get_token(self) -> str:
        creds = base64.b64encode(f'{self._key}:{self._secret}'.encode()).decode()
        resp = _requests.get(
            f'{self._base}/oauth/v1/generate?grant_type=client_credentials',
            headers={'Authorization': f'Basic {creds}'},
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()['access_token']

    def _b2c_payment(self, token: str, phone: str, amount: float, request_id: int) -> dict:
        from django.conf import settings
        callback_url = f'{getattr(settings, "TRACKER_URL", "")}/webhooks/mpesa/b2c/'
        resp = _requests.post(
            f'{self._base}/mpesa/b2c/v3/paymentrequest',
            json={
                'InitiatorName': self._initiator,
                'SecurityCredential': self._credential,
                'CommandID': 'BusinessPayment',
                'Amount': int(amount),
                'PartyA': self._shortcode,
                'PartyB': phone,
                'Remarks': f'Nexora payout #{request_id}',
                'QueueTimeOutURL': callback_url,
                'ResultURL': callback_url,
                'Occassion': '',
            },
            headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()
