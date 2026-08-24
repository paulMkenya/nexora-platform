"""Idempotent seed for the Hypernet BoxType and one Hypernet LeadBuyer box.

A management command rather than a data migration, deliberately: the
existing op-brandy BoxType was not created by a migration either (0005 only
creates the table), and a data migration here would have to be sequenced
against other in-flight leadgen migrations. Re-running this is safe —
everything is update_or_create keyed on slug.

The BoxType is named 'Hypernet', not 'desperados.hn-crm.com', so a second
Hypernet box on a different domain reuses it: only base_url, the API key
and the affc/bxc/vtc constants differ per box, never the connector
behavior.

Usage:
    # BoxType only (safe, no credentials involved)
    python manage.py seed_hypernet_box

    # BoxType + the desperados buyer, reading the key from the environment
    HYPERNET_API_KEY=... python manage.py seed_hypernet_box \\
        --buyer --brand chainpulse \\
        --affc AFF-... --bxc BX-... --vtc VT-... \\
        --base-url https://desperados.hn-crm.com

The API key is read from $HYPERNET_API_KEY and never accepted as a command
-line argument — argv is visible in `ps` output and lands in shell history.
It is stored via LeadBuyer.set_api_key() (Fernet, nexora.crypto), never in
plaintext.
"""
import os

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from leadgen.models import BoxType, LeadBuyer

BOX_SLUG = 'hypernet'

# Our field name -> Hypernet's, as DOTTED PATHS. HypernetConnector reads a
# dot as nesting (see connectors._set_path) so this flat mapping can express
# Hypernet's nested `profile` object; the base connector cannot.
DEFAULT_FIELD_MAPPING = {
    'firstname': 'profile.firstName',
    'lastname': 'profile.lastName',
    'email': 'profile.email',
    'phone': 'profile.phone',
    'vertical': 'funnel',
    'source_id': 'subId',
    # OPT-IN source (connectors.OPT_IN_LEAD_FIELDS): Lead.language -> their
    # `lang`. Hypernet documents `lang` as "language code of lead", and their
    # call centres route capacity on it, but until this mapping existed the
    # only `lang` we ever sent was the static 'en' in extra_payload_fields —
    # so an affiliate who correctly sent language="PL" had it silently
    # dropped, and our own API doc promised otherwise.
    #
    # Statics still supply the default: build_extra_payload OMITS a mapped-
    # but-empty source, so a lead with no language leaves the box's 'en'
    # untouched. HypernetConnector.LOWERCASE_KEYS folds the case, because we
    # document language as ISO 639-1 with upper-case examples and they ask
    # for lower-case.
    'language': 'lang',
}

# Hypernet's `registration.status` -> Nexora canonical_status.
#
# EVERY ENTRY HERE WAS OBSERVED ON A LIVE BOX, none is copied from their docs
# (which do not publish the vocabulary at all). As of 2026-08-24 the only two
# values Hypernet has ever returned across 43 recorded status reports are
# 'sent' and 'deposited'; both were re-verified against the Badboys box the
# day this mapping was written.
#
# READ `registration.status`, NOT `rawStatus`. The sibling `rawStatus` is the
# broker's own free text ('Test Lead' on the QA box) and varies per broker
# configuration, so it is unmappable by construction — see
# HypernetConnector.parse_status_sync_results.
#
# DELIBERATELY INCOMPLETE. A status that is missing here does not get guessed
# at: map_buyer_status returns needs_review=True, the lead is flagged for a
# human and canonical_status is left alone (spec §3.2, "do NOT silently drop
# or guess"). That is the correct way to learn the rest of the vocabulary —
# add an entry when the flag tells you a real value showed up, never before.
#
# WHY THIS WAS EMPTY UNTIL NOW: the box was seeded when status sync did not
# exist for it (supports_status_sync was False), so there was nothing to map.
# Sync was implemented later and this was never revisited, which meant every
# Hypernet deposit landed as needs_review and canonical_status stayed blank —
# the affiliate pull API (GET /api/leads?status=ftd) could not see a single
# conversion. The mapping is what closes that loop.
DEFAULT_STATUS_MAPPING = {
    'sent': 'pending',
    'deposited': 'ftd',
}


class Command(BaseCommand):
    help = 'Create or update the Hypernet BoxType, and optionally one Hypernet LeadBuyer.'

    def add_arguments(self, parser):
        parser.add_argument('--buyer', action='store_true',
                            help='Also create/update a LeadBuyer row (needs --brand and the codes).')
        parser.add_argument('--brand', help='Brand slug the buyer belongs to.')
        parser.add_argument('--slug', default='hypernet-desperados', help='LeadBuyer slug.')
        parser.add_argument('--name', default='Hypernet - desperados', help='LeadBuyer display name.')
        parser.add_argument('--base-url', default='https://desperados.hn-crm.com')
        parser.add_argument('--affc', help='Hypernet affiliate code for this box.')
        parser.add_argument('--bxc', help='Hypernet box code.')
        parser.add_argument('--vtc', help='Hypernet vertical code.')
        parser.add_argument('--lang', default='en')
        parser.add_argument('--landing-url', default='', help='Optional static landingURL for this box.')
        # Rate limits default to op-brandy's live values (burst 60, 5 tokens
        # per 2s) — Hypernet documents none, so the known-good policy of the
        # other box is a safer starting point than the model defaults.
        parser.add_argument('--rate-burst', type=int, default=60)
        parser.add_argument('--rate-refill-tokens', type=int, default=5)
        parser.add_argument('--rate-refill-seconds', type=int, default=2)

    @transaction.atomic
    def handle(self, *args, **options):
        box_type, created = BoxType.objects.update_or_create(
            slug=BOX_SLUG,
            defaults=dict(
                name='Hypernet',
                version=1,
                description='Hypernet-CRM lead-buying platform (HTN-AFF-SDK).',
                connector_class='leadgen.connectors.HypernetConnector',
                auth_type=BoxType.AUTH_API_KEY_HEADER,
                auth_param_name='x-api-key',
                single_endpoint_path='/api/external/integration/lead',
                # No batch endpoint is documented. Blank path + batch_max_size=1
                # both make LeadBuyer.supports_batch False; HypernetConnector
                # also refuses inject_batch() outright.
                batch_endpoint_path='',
                fetch_endpoint_path='/api/external/integration/lead',
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

        if not hasattr(LeadBuyer, 'extra_payload_fields'):
            raise CommandError(
                'LeadBuyer.extra_payload_fields does not exist yet — run its migration first. '
                'Without it the affc/bxc/vtc constants have nowhere to live and every '
                'injection would be rejected by Hypernet.')

        missing = [f for f in ('brand', 'affc', 'bxc', 'vtc') if not options.get(f)]
        if missing:
            raise CommandError(f'--buyer requires: {", ".join("--" + m for m in missing)}')

        api_key = os.environ.get('HYPERNET_API_KEY', '').strip()
        if not api_key:
            raise CommandError(
                'Set HYPERNET_API_KEY in the environment. It is deliberately not a CLI '
                'argument — argv is visible in `ps` and recorded in shell history.')

        try:
            brand = Brand.objects.get(slug=options['brand'])
        except Brand.DoesNotExist:
            raise CommandError(f'No brand with slug {options["brand"]!r}.')

        extra = {
            'affc': options['affc'],
            'bxc': options['bxc'],
            'vtc': options['vtc'],
            'lang': options['lang'],
            'landingLang': options['lang'],
        }
        if options['landing_url']:
            extra['landingURL'] = options['landing_url']

        buyer, created = LeadBuyer.objects.update_or_create(
            slug=options['slug'],
            defaults=dict(
                box_type=box_type,
                brand=brand,
                name=options['name'],
                base_url=options['base_url'],
                is_active=True,
                # Starts OFF. Flip to True only after a manual test injection
                # comes back 201/success and the LeadInjection row reads
                # 'delivered' — the proof the envelope mismatch is fixed.
                auto_inject=False,
                extra_payload_fields=extra,
                # Empty: the BoxType's default_field_mapping already covers
                # this box. Overrides belong here only for a real quirk.
                field_mapping={},
                status_mapping={},
            ),
        )
        buyer.set_api_key(api_key)
        buyer.save(update_fields=['api_key_encrypted'])

        self.stdout.write(self.style.SUCCESS(
            f'LeadBuyer {buyer.slug!r} {"created" if created else "updated"} (id={buyer.pk}), '
            f'brand={brand.slug}, auto_inject=False.'))
        self.stdout.write(
            'Next: run a manual test injection and confirm the LeadInjection row reads '
            "status='delivered' before enabling auto_inject.")
