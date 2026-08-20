"""Give the three existing BoxTypes the variable schema they always implicitly had.

This is the whole point of the feature, applied retroactively: what a Hypernet
box needs — affc, bxc, vtc, a funnel label, a landing URL — was real all along,
it was just never written anywhere the software could read. It lived in a
hard-coded dict inside seed_hypernet_box.py, in connector class attributes, and
in whoever last did an onboarding.

Idempotent and keyed on slug. Only fills a schema that is EMPTY: a template
someone has since edited by hand is left alone, because their edit is newer
information than this file.

A management command rather than a data migration, matching seed_hypernet_box
and seed_trackbox_box — the existing BoxTypes were not created by a migration
either, and a data migration here would have to be sequenced against other
in-flight leadgen migrations.
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from leadgen.models import BoxType

# name / label / help / required / secret. `help` is written for an operator
# onboarding a buyer, not for a developer reading the source — it is the text
# that replaces asking someone who has done it before.
SCHEMAS = {
    'hypernet': [
        {'name': 'affc', 'label': 'Affiliate code (affc)', 'required': True,
         'help': 'Issued by the box per affiliate account, e.g. AFF-XXXXXXXX. '
                 'Ask the buyer for it — it identifies us to them.'},
        {'name': 'bxc', 'label': 'Box code (bxc)', 'required': True,
         'help': 'Identifies this specific box/hub, e.g. BX-XXXXXXXXXX. '
                 'Different per box even on the same platform.'},
        {'name': 'vtc', 'label': 'Vertical code (vtc)', 'required': True,
         'help': 'The vertical this box buys, e.g. VT-XXXXXXXXXX. Often shared '
                 'across several boxes from the same provider.'},
        {'name': 'funnel', 'label': 'Funnel / vertical', 'required': True,
         'choices': 'verticals',
         'help': 'REQUIRED by this platform, and the label they optimise on in '
                 'their own reporting. Picked from the vertical taxonomy so it '
                 "matches what leads carry; pin it if a lead's own vertical "
                 'must not be able to overwrite it.'},
        {'name': 'landingURL', 'label': 'Landing URL', 'required': True,
         'help': 'The page the consumer came through. Usually your offer lander, '
                 'e.g. https://your-domain/l/<offer_id>/'},
        {'name': 'lang', 'label': 'Default language', 'required': False,
         'default': 'en',
         'help': "Lower-case ISO 639-1. Used when a lead carries no language of "
                 "its own; a lead's own language wins."},
        {'name': 'landingLang', 'label': 'Landing language', 'required': False,
         'default': 'en', 'help': 'Lower-case ISO 639-1. The language of the lander itself.'},
    ],
    'trackbox': [
        {'name': 'ai', 'label': 'Affiliate ID (ai)', 'required': True,
         'help': 'Your numeric affiliate id with this box.'},
        {'name': 'ci', 'label': 'Campaign ID (ci)', 'required': True,
         'help': 'The campaign this traffic is booked against.'},
        {'name': 'gi', 'label': 'Group ID (gi)', 'required': True,
         'help': 'The box/group id they route your leads into.'},
        {'name': 'so', 'label': 'Source label', 'required': False,
         'help': 'Shown in their reporting as the traffic source. A per-funnel '
                 'value is far more useful to them than one constant.'},
        {'name': 'vertical', 'label': 'Default vertical', 'required': False,
         'choices': 'verticals',
         'help': 'Used when a lead carries no vertical of its own.'},
        {'name': 'MPC_1', 'label': 'Passthrough MPC_1', 'required': False,
         'help': 'Optional passthrough slot they echo back on reporting.'},
    ],
    'op-brandy-v1': [
        {'name': 'source', 'label': 'Source label', 'required': False,
         'help': 'Optional label identifying this traffic in their reporting.'},
    ],
}


class Command(BaseCommand):
    help = 'Backfill variable_schema on the built-in BoxTypes (idempotent, empty-only).'

    def add_arguments(self, parser):
        parser.add_argument('--force', action='store_true',
                            help='Overwrite a schema that has already been edited. '
                                 'Off by default: a hand edit is newer information than this file.')

    @transaction.atomic
    def handle(self, *args, **options):
        for slug, schema in SCHEMAS.items():
            box = BoxType.objects.filter(slug=slug).first()
            if box is None:
                self.stdout.write(f'  {slug}: not present here, skipped.')
                continue
            if box.variable_schema and not options['force']:
                self.stdout.write(
                    f'  {slug}: already has {len(box.variable_schema)} variable(s), left alone '
                    f'(--force to overwrite).')
                continue
            box.variable_schema = schema
            box.full_clean()      # validates the schema AND the connector registry
            box.save(update_fields=['variable_schema', 'updated_at'])
            self.stdout.write(self.style.SUCCESS(
                f'  {slug}: {len(schema)} variable(s) written.'))
        self.stdout.write('Done.')
