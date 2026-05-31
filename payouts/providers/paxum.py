"""
Paxum CSV batch payout provider.
Paxum doesn't have a real-time API; export a CSV and upload manually.
PAXUM_ACCOUNT_EMAIL env var enables the provider (blank=disabled).
"""
import csv
import io
import logging
import os

logger = logging.getLogger(__name__)


class PaxumProvider:
    def __init__(self):
        self._account = os.environ.get('PAXUM_ACCOUNT_EMAIL', '').strip()

    def is_enabled(self) -> bool:
        return bool(self._account)

    def send_payout(self, payout_request, pm) -> bool:
        from payouts.models import STATUS_APPROVED
        details = pm.details if pm else {}
        email = details.get('email', '')
        if not email:
            payout_request.notes = 'Missing Paxum email'
            return False
        payout_request.status = STATUS_APPROVED
        payout_request.notes = 'Queued for Paxum CSV batch export'
        return True

    def build_csv(self, payout_requests) -> str:
        """Generate Paxum bulk payment CSV content."""
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(['Email', 'Amount', 'Currency', 'Note'])
        for req in payout_requests:
            pm = req.payout_method
            email = pm.details.get('email', '') if pm else ''
            writer.writerow([email, f'{req.amount:.2f}', req.currency, f'Nexora payout #{req.pk}'])
        return buf.getvalue()
