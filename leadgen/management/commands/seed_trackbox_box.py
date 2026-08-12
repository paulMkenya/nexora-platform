"""Idempotent seed for the TrackBox BoxType and one TrackBox LeadBuyer box.

A management command rather than a data migration, for the same reason
seed_hypernet_box.py is one: the existing BoxTypes were not created by
migrations either, and a data migration here would have to be sequenced
against other in-flight leadgen migrations. Re-running is safe — everything
is update_or_create keyed on slug.

The BoxType is named 'TrackBox', not after any one instance's domain, so a
second TrackBox brand reuses it: only base_url, the credentials and the
ai/ci/gi constants differ per box, never the connector behavior.

Usage:
    # BoxType only (safe, no credentials involved)
    python manage.py seed_trackbox_box

    # BoxType + one buyer. All three secrets come from the environment.
    TRACKBOX_API_KEY=... TRACKBOX_USERNAME=... TRACKBOX_PASSWORD=... \\
    python manage.py seed_trackbox_box \\
        --buyer --brand <brand-slug> \\
        --base-url https://platform.traffixworld.com \\
        --ai 2958839 --ci 1 --gi 843 --so exxtraffic

NONE of the three secrets is accepted as a command-line argument — argv is
visible in `ps` output and lands in shell history. The API key is stored via
LeadBuyer.set_api_key() and the username/password via
set_extra_credentials(); all three are Fernet-encrypted (nexora.crypto),
never plaintext.
"""
import os

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from leadgen.models import BoxType, LeadBuyer

BOX_SLUG = 'trackbox'

# Our field name -> TrackBox's. Flat: TrackBox takes every field at the top
# level of the signup body (unlike Hypernet's nested `profile`), so no
# dotted paths are involved.
#
# `vertical` is deliberately ABSENT. TrackBox's nearest equivalent is `so`
# (the funnel name shown in their reports), but `so` identifies the traffic
# SOURCE for this box and is agreed per-buyer — it is seeded as a static
# constant below rather than overwritten per lead. A brand that genuinely
# wants the lead's own vertical in a TrackBox field should map it to one of
# the MPC_1..MPC_12 free parameters via LeadBuyer.field_mapping.
DEFAULT_FIELD_MAPPING = {
    'firstname': 'firstname',
    'lastname': 'lastname',
    'email': 'email',
    'phone': 'phone',
    'source_id': 'sub',
}

# TrackBox's own status vocabulary -> Nexora's canonical_status
# (leadgen/canonical_status.py). Seeded from the status names their help
# centre uses in its reporting screenshots ("new", "no answer", FTD).
#
# Deliberately partial. Nothing here is guessed at from a status this box
# has not been SEEN to emit: an unmapped status is not silently dropped —
# leadgen.status_sync flags it via Lead.canonical_status_needs_review (spec
# §3.2, "do NOT silently drop or guess"), which is how the remaining values
# get discovered and added. A wrong mapping, by contrast, would convert a
# lead's status wrongly and silently, and 'ftd' is the value that BILLS.
DEFAULT_STATUS_MAPPING = {
    'new': 'new',
    'no answer': 'no_answer',
    'callback': 'callback',
    'wrong number': 'wrong_number',
    'not interested': 'not_interested',
    'do not call': 'do_not_call',
    'ftd': 'ftd',
    'deposit': 'ftd',
}


class Command(BaseCommand):
    help = 'Create or update the TrackBox BoxType, and optionally one TrackBox LeadBuyer.'

    def add_arguments(self, parser):
        parser.add_argument('--buyer', action='store_true',
                            help='Also create/update a LeadBuyer row (needs --brand and the codes).')
        parser.add_argument('--brand', help='Brand slug the buyer belongs to.')
        parser.add_argument('--slug', default='trackbox-traffixworld', help='LeadBuyer slug.')
        parser.add_argument('--name', default='TrackBox - Traffix World', help='LeadBuyer display name.')
        parser.add_argument('--base-url', default='https://platform.traffixworld.com')
        parser.add_argument('--ai', help='TrackBox affiliate id for this box ("ask your trackbox partner").')
        parser.add_argument('--ci', default='1', help='TrackBox campaign id.')
        parser.add_argument('--gi', help='TrackBox gi value ("ask your trackbox partner").')
        parser.add_argument('--so', default='',
                            help='Funnel/source name shown in their reports, e.g. the affiliate '
                                 'sending this traffic.')
        parser.add_argument('--lg', default='EN', help='Language code sent with every lead.')
        # TrackBox documents no rate-limit policy. Starting from op-brandy's
        # known-good live values (burst 60, 5 tokens per 2s) rather than the
        # model defaults, exactly as seed_hypernet_box does — a documented
        # policy from a comparable box beats a guess.
        parser.add_argument('--rate-burst', type=int, default=60)
        parser.add_argument('--rate-refill-tokens', type=int, default=5)
        parser.add_argument('--rate-refill-seconds', type=int, default=2)

    @transaction.atomic
    def handle(self, *args, **options):
        box_type, created = BoxType.objects.update_or_create(
            slug=BOX_SLUG,
            defaults=dict(
                name='TrackBox',
                version=1,
                description=(
                    'TrackBox by Tigloo. Failures arrive as HTTP 200 with the real outcome '
                    'in the body — see leadgen.connectors.TrackBoxConnector and '
                    'docs/trackbox-integration.md.'),
                connector_class='leadgen.connectors.TrackBoxConnector',
                # The API key rides here; the username/password pair it needs
                # ALONGSIDE this lives encrypted on the LeadBuyer and is added
                # by TrackBoxConnector.extra_auth_headers().
                auth_type=BoxType.AUTH_API_KEY_HEADER,
                auth_param_name='x-api-key',
                single_endpoint_path='/api/signup/procform',
                # No batch endpoint is documented. Blank path + batch_max_size=1
                # both make LeadBuyer.supports_batch False; TrackBoxConnector
                # also refuses inject_batch() outright.
                batch_endpoint_path='',
                fetch_endpoint_path='/api/pull/customers',
                deposits_endpoint_path='',
                batch_max_size=1,
                rate_limit_burst=options['rate_burst'],
                rate_limit_refill_tokens=options['rate_refill_tokens'],
                rate_limit_refill_seconds=options['rate_refill_seconds'],
                default_field_mapping=DEFAULT_FIELD_MAPPING,
                default_status_mapping=DEFAULT_STATUS_MAPPING,
            ),
        )
        self.stdout.write(self.style.SUCCESS(
            f'BoxType {BOX_SLUG!r} {"created" if created else "updated"} (id={box_type.pk}).'))

        if not options['buyer']:
            self.stdout.write('No --buyer flag; BoxType only. Done.')
            return

        self._seed_buyer(box_type, options)

    def _seed_buyer(self, box_type, options):
        from brands.models import Brand

        if not hasattr(LeadBuyer, 'extra_credentials_encrypted'):
            raise CommandError(
                'LeadBuyer.extra_credentials_encrypted does not exist yet — run its migration '
                'first. Without it the username/password have nowhere to live and every '
                'request would be rejected by TrackBox.')

        missing = [f for f in ('brand', 'ai', 'gi') if not options.get(f)]
        if missing:
            raise CommandError(f'--buyer requires: {", ".join("--" + m for m in missing)}')

        secrets_from_env = {
            'api_key': os.environ.get('TRACKBOX_API_KEY', '').strip(),
            'username': os.environ.get('TRACKBOX_USERNAME', '').strip(),
            'password': os.environ.get('TRACKBOX_PASSWORD', ''),
        }
        absent = sorted(k for k, v in secrets_from_env.items() if not v)
        if absent:
            raise CommandError(
                f'Set {", ".join("TRACKBOX_" + a.upper() for a in absent)} in the environment. '
                'They are deliberately not CLI arguments — argv is visible in `ps` and '
                'recorded in shell history.')

        try:
            brand = Brand.objects.get(slug=options['brand'])
        except Brand.DoesNotExist:
            raise CommandError(f'No brand with slug {options["brand"]!r}.')

        # Their signup body's fixed per-box constants. Every one of these is
        # a property of the BUYER, not of a lead, so none is derivable from
        # a Lead row and none belongs in field_mapping.
        extra = {
            'ai': str(options['ai']),
            'ci': str(options['ci']),
            'gi': str(options['gi']),
            'lg': options['lg'],
        }
        if options['so']:
            extra['so'] = options['so']

        buyer, created = LeadBuyer.objects.update_or_create(
            slug=options['slug'],
            defaults=dict(
                box_type=box_type,
                brand=brand,
                name=options['name'],
                base_url=options['base_url'],
                is_active=True,
                # Starts OFF. Flip to True only after a manual test injection
                # comes back with status:true and the LeadInjection row reads
                # 'delivered' — on this box especially, because it answers 200
                # to failures and the credentials cannot be verified any other
                # way.
                auto_inject=False,
                extra_payload_fields=extra,
                # Empty: the BoxType's defaults already cover this box.
                # Overrides belong here only for a real per-brand quirk.
                field_mapping={},
                status_mapping={},
            ),
        )
        buyer.set_api_key(secrets_from_env['api_key'])
        buyer.set_extra_credentials({
            'username': secrets_from_env['username'],
            'password': secrets_from_env['password'],
        })
        buyer.save(update_fields=['api_key_encrypted', 'extra_credentials_encrypted'])

        self.stdout.write(self.style.SUCCESS(
            f'LeadBuyer {buyer.slug!r} {"created" if created else "updated"} (id={buyer.pk}), '
            f'brand={brand.slug}, auto_inject=False.'))
        self.stdout.write(
            'Next: run a manual test injection and confirm the LeadInjection row reads '
            "status='delivered' before enabling auto_inject. This box returns HTTP 200 even "
            'when it rejects your credentials, so a "successful" HTTP call proves nothing on '
            'its own — read the stored response.')
