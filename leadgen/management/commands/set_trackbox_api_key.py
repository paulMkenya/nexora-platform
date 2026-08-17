"""Set a TrackBox buyer's ``x-api-key`` — and prove it works before storing it.

WHY THIS EXISTS, and why it is not just `seed_trackbox_box --buyer`: the
Traffix World integration has been blocked since 2026-08-12 on a single
missing secret. Pushing leads works without a valid ``x-api-key``; pulling
statuses does not (see docs/trackbox-integration.md §2), so we deliver leads
whose deposits never come back. Everything else about that buyer — username,
password, ai/ci/gi, base_url — is already correct and PROVEN by live
deliveries. The onboarding command re-seeds the whole row and demands all
three secrets from the environment, so using it to change one field means
re-typing a working password next to a working injection path. This command
changes exactly one field.

VERIFY BEFORE WRITE. The candidate key is tested against the live pull
endpoint FIRST and persisted only if the box accepts it, so a wrong key never
reaches the database. That ordering matters more on this box than on most:
it answers ``200 OK`` to a credential rejection (§1), so "it saved fine and
nothing errored" is not evidence of anything, and a stored-but-wrong key is
indistinguishable from the current broken state until the next Beat tick.

THE ERROR MESSAGE ON THIS BOX LIES. With an invalid key it answers "User and
password doesnt match" whether the username/password are right or deliberately
wrong — verified by probe on 2026-08-17. Do not let that message send anyone
back to the vendor asking about the password.

Usage:
    # dry run — probe the live box, store nothing
    TRACKBOX_API_KEY=... python manage.py set_trackbox_api_key --check

    # verify, then persist only on success
    TRACKBOX_API_KEY=... python manage.py set_trackbox_api_key

The key comes from the environment, never argv — argv is visible in `ps` and
lands in shell history. Same rule as seed_trackbox_box.
"""
import os

import requests
from django.core.management.base import BaseCommand, CommandError

from leadgen.models import LeadBuyer

# The value printed in TrackBox's public documentation. It is not a credential;
# it was tried against the live box on 2026-08-12 and rejected exactly like a
# random string. Refused by name so nobody re-introduces the current outage
# while believing they have fixed it.
DOC_PLACEHOLDER_KEY = '2643889w34df345676ssdas323tgc738'

PULL_PATH = '/api/pull/customers'


class Command(BaseCommand):
    help = "Set a TrackBox buyer's x-api-key, verifying it against the live box before storing."

    def add_arguments(self, parser):
        parser.add_argument('--slug', default='trackbox-traffixworld', help='LeadBuyer slug.')
        parser.add_argument('--check', action='store_true',
                            help='Probe only — never write, whatever the result.')
        parser.add_argument('--force', action='store_true',
                            help='Store even if verification fails. For a key known good while '
                                 'their box is down; you own the outcome.')
        parser.add_argument('--timeout', type=int, default=45)

    def handle(self, *args, **options):
        candidate = os.environ.get('TRACKBOX_API_KEY', '').strip()
        if not candidate:
            raise CommandError(
                'Set TRACKBOX_API_KEY in the environment (not argv — it would land in '
                'shell history and `ps`).')
        if candidate == DOC_PLACEHOLDER_KEY:
            raise CommandError(
                'That is the placeholder from TrackBox\'s public docs, not a credential — it is '
                'what is stored right now and why status sync 401s. Ask Traffix World for the '
                'x-api-key issued for the API user on platform.traffixworld.com.')

        try:
            buyer = LeadBuyer.objects.select_related('box_type').get(slug=options['slug'])
        except LeadBuyer.DoesNotExist:
            raise CommandError(f'No LeadBuyer with slug {options["slug"]!r}.') from None

        credentials = buyer.get_extra_credentials() or {}
        username = str(credentials.get('username') or '').strip()
        password = str(credentials.get('password') or '')
        if not username or not password:
            raise CommandError(
                f'Buyer {buyer.slug!r} has no username/password stored, so this key cannot be '
                'verified on its own. Run seed_trackbox_box --buyer first.')

        self.stdout.write(f'buyer     : {buyer.name} (id={buyer.pk}, brand={buyer.brand_id})')
        self.stdout.write(f'endpoint  : {buyer.base_url.rstrip("/")}{PULL_PATH}')
        self.stdout.write(f'username  : {username}')
        self.stdout.write(f'candidate : {len(candidate)} chars, ends {candidate[-4:]!r}\n')

        accepted, detail = self._verify(buyer, candidate, username, password, options['timeout'])

        if accepted:
            self.stdout.write(self.style.SUCCESS(f'VERIFIED — the box accepted this key. {detail}'))
        else:
            self.stdout.write(self.style.ERROR(f'REJECTED — {detail}'))

        if options['check']:
            self.stdout.write('\n--check: nothing written.')
            return

        if not accepted and not options['force']:
            raise CommandError(
                'Not storing a key the box rejects — that would replace one broken state with '
                'another and look fixed. Re-run with --force only if you know this key is good '
                'and their box is simply down.')

        buyer.set_api_key(candidate)
        buyer.save(update_fields=['api_key_encrypted', 'updated_at'])
        self.stdout.write(self.style.SUCCESS(f'\nStored on buyer {buyer.slug!r}.'))
        self.stdout.write(
            'Status sync runs on the 30-minute Beat tick. To pull immediately:\n'
            '  docker exec nexora-web python manage.py shell -c '
            '"from leadgen.models import LeadBuyer; from leadgen.tasks import '
            'sync_buyer_statuses_for_buyer; '
            f'print(sync_buyer_statuses_for_buyer(LeadBuyer.objects.get(slug=\'{buyer.slug}\')))"')

    def _verify(self, buyer, candidate, username, password, timeout):
        """(accepted, human_detail) for `candidate` against the live pull endpoint.

        Deliberately builds the request by hand instead of going through the
        connector: the connector reads the key off the buyer, so using it would
        mean writing the candidate to the database to test it — the exact
        ordering this command exists to avoid.
        """
        url = buyer.base_url.rstrip('/') + PULL_PATH
        headers = {
            'Content-Type': 'application/json',
            'x-trackbox-username': username,
            'x-trackbox-password': password,
            'x-api-key': candidate,
        }
        # A narrow window: this asks "do you accept these credentials", not
        # "give me data", so it should stay cheap on their side.
        body = {'DateFrom': '2026-01-01', 'DateTo': '2026-01-02'}

        try:
            response = requests.post(url, json=body, headers=headers, timeout=timeout)
        except requests.RequestException as exc:
            return False, f'could not reach the box: {type(exc).__name__}: {exc}'

        try:
            parsed = response.json()
        except ValueError:
            return False, f'HTTP {response.status_code}, non-JSON body: {response.text[:160]!r}'

        # Their success and error bodies differ by the presence of `status`:
        # errors carry `status: false`, a good pull carries data/meta and no
        # `status` key at all. Same test as TrackBoxConnector._is_soft_error —
        # kept in sync with it deliberately, not reimplemented differently.
        if isinstance(parsed, dict) and 'status' in parsed and not parsed['status']:
            code = parsed.get('code')
            message = str(parsed.get('message') or '')[:200]
            hint = ''
            if str(code) in {'401', '403'}:
                hint = ('\n  NOTE: on this box that message is emitted for a bad x-api-key even '
                        'when the username/password are correct — it is not evidence about them.')
            return False, f'HTTP {response.status_code}, code={code}: {message}{hint}'

        rows = parsed.get('data') if isinstance(parsed, dict) else None
        count = len(rows) if isinstance(rows, list) else 'unknown'
        return True, f'HTTP {response.status_code}, no error body (rows in probe window: {count}).'
