"""Fail-fast preflight for the NOWPayments Mass Payouts sandbox integration.

This is the FIRST thing a human runs after deploying PR #10. It answers the open
question — does the NOWPayments *sandbox* actually expose the custody/mass-payout
endpoints we need — BEFORE we build the dispatch wiring (PR #11).

It prints a PASS/FAIL checklist and NEVER prints any secret value (only the names
of missing settings, and at most a token *length*). It talks to the configured
(sandbox by default) base URL; the client's own mainnet guard refuses a
production-looking URL unless explicitly overridden.

Usage (inside the web container):
    python manage.py nowpayments_preflight
"""
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.management.base import BaseCommand

from payouts.providers.nowpayments import NowPaymentsError, NowPaymentsPayoutClient
from payouts.providers.nowpayments.base import SANDBOX_HOST, _looks_like_production

# Settings the live preflight needs. (IPN_SECRET / IPN_CALLBACK_URL are PR #11 and
# are reported as informational, not required for preflight.)
REQUIRED_SETTINGS = [
    'NOWPAYMENTS_SANDBOX_API_KEY',
    'NOWPAYMENTS_SANDBOX_EMAIL',
    'NOWPAYMENTS_SANDBOX_PASSWORD',
    'NOWPAYMENTS_SANDBOX_TOTP_SECRET',
]
INFO_SETTINGS = [
    'NOWPAYMENTS_SANDBOX_IPN_SECRET',
    'NOWPAYMENTS_SANDBOX_IPN_CALLBACK_URL',
]

# An obviously-invalid test address used only to probe that the validate-address
# endpoint EXISTS. Any response (success or error) proves the endpoint is there.
PROBE_ADDRESS = 'PREFLIGHT-PROBE-NOT-A-REAL-ADDRESS'


class Command(BaseCommand):
    help = 'Preflight the NOWPayments Mass Payouts sandbox integration (no real payout).'

    def handle(self, *args, **options):
        self.stdout.write('NOWPayments sandbox preflight')
        self.stdout.write('=' * 60)

        ok = True
        ok &= self._check_settings()
        ok &= self._check_mainnet_guard()

        client = self._build_client()
        if client is None:
            self._fail('Could not construct client — aborting reachability checks.')
            self._summary(False)
            return

        ok &= self._check_status(client)
        ok &= self._check_auth(client)
        ok &= self._check_balance(client)
        ok &= self._check_payout_endpoint(client)

        self._summary(ok)

    # --- individual checks -----------------------------------------------------

    def _check_settings(self) -> bool:
        missing = [name for name in REQUIRED_SETTINGS if not getattr(settings, name, '')]
        if missing:
            self._fail(f'Required settings missing: {", ".join(missing)} '
                       '(names only — never set values are printed).')
            ok = False
        else:
            self._pass('All required settings are present.')
            ok = True
        # Informational (PR #11) — never fails preflight.
        info_missing = [name for name in INFO_SETTINGS if not getattr(settings, name, '')]
        if info_missing:
            self._info(f'PR #11 settings not yet set (ok for now): {", ".join(info_missing)}')
        return ok

    def _check_mainnet_guard(self) -> bool:
        base_url = getattr(settings, 'NOWPAYMENTS_BASE_URL', '')
        allow_mainnet = getattr(settings, 'NOWPAYMENTS_ALLOW_MAINNET', False)
        is_prod = _looks_like_production(base_url)
        target = 'PRODUCTION/MAINNET' if is_prod else f'sandbox ({SANDBOX_HOST})'
        self._info(f'Target environment: {target}. NOWPAYMENTS_ALLOW_MAINNET={allow_mainnet}.')
        if is_prod and not allow_mainnet:
            # The client would refuse to build; report it here as a clear FAIL.
            self._fail('Base URL looks like production but the mainnet flag is off — '
                       'the client will refuse to initialise (money-safety guard).')
            return False
        if is_prod:
            self._info('WARNING: targeting mainnet by explicit opt-in.')
        self._pass(f'Mainnet guard OK ({target}).')
        return True

    def _check_status(self, client) -> bool:
        try:
            client.get_status()
        except NowPaymentsError as exc:
            self._fail(f'GET /status unreachable: {exc}')
            return False
        self._pass('GET /status — API reachable.')
        return True

    def _check_auth(self, client) -> bool:
        try:
            token = client._get_jwt(force_refresh=True)
        except NowPaymentsError as exc:
            self._fail(f'POST /auth — could not obtain JWT: {exc}')
            return False
        self._pass(f'POST /auth — JWT obtained (token length={len(token)}).')
        return True

    def _check_balance(self, client) -> bool:
        try:
            client.get_balance()
        except NowPaymentsError as exc:
            self._fail(f'GET /balance — custody endpoint failed: {exc} '
                       '(this is the key unknown: payout/custody may be unavailable in sandbox).')
            return False
        self._pass('GET /balance — custody/balance endpoint responds.')
        return True

    def _check_payout_endpoint(self, client) -> bool:
        """Probe payout-endpoint existence WITHOUT creating a real payout.

        validate-address with a junk address proves the endpoint exists: a clean
        2xx OR a 4xx validation error both confirm presence. Only a transport
        failure or a 5xx counts as "does not respond".
        """
        currency = getattr(settings, 'NOWPAYMENTS_DEFAULT_CURRENCY', 'usdttrc20')
        try:
            client.validate_address(PROBE_ADDRESS, currency)
            self._pass('POST /payout/validate-address — endpoint exists (accepted probe).')
            return True
        except NowPaymentsError as exc:
            if exc.status_code is not None and 400 <= exc.status_code < 500:
                self._pass('POST /payout/validate-address — endpoint exists '
                           f'(rejected junk probe with {exc.status_code}, as expected).')
                return True
            self._fail(f'POST /payout/validate-address — endpoint did not respond: {exc}')
            return False

    # --- helpers ---------------------------------------------------------------

    def _build_client(self):
        try:
            return NowPaymentsPayoutClient()
        except ImproperlyConfigured as exc:
            self._fail(f'Client init refused (mainnet guard / config): {exc}')
            return None

    def _pass(self, msg):
        self.stdout.write(self.style.SUCCESS(f'  PASS  {msg}'))

    def _fail(self, msg):
        self.stdout.write(self.style.ERROR(f'  FAIL  {msg}'))

    def _info(self, msg):
        self.stdout.write(f'  ----  {msg}')

    def _summary(self, ok: bool):
        self.stdout.write('=' * 60)
        if ok:
            self.stdout.write(self.style.SUCCESS(
                'PREFLIGHT PASSED — sandbox supports the endpoints PR #11 needs.'))
        else:
            self.stdout.write(self.style.ERROR(
                'PREFLIGHT FAILED — resolve the FAIL lines above before building PR #11.'))
