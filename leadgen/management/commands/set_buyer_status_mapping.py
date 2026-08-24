"""Merge entries into one LeadBuyer's own status_mapping.

WHY A COMMAND AND NOT A CONSTANT. A box's raw disposition vocabulary is
per-BROKER, not per-platform: two Hypernet boxes run different call centres
with different labels, which is exactly why LeadBuyer.status_mapping exists as
a field that overrides BoxType.default_status_mapping. Shared, normalized
vocabulary belongs in the seed command for its BoxType; anything a single
broker's agents type belongs here, in data.

IT MERGES, NEVER REPLACES. `update_or_create(defaults={...})` semantics on a
JSONField are how a mapping silently loses entries — see the Hypernet BoxType,
which sat on `{}` for four days because a seed passed an empty literal. Keys
given on the command line win; keys already present and not mentioned survive.

Usage:
    python manage.py set_buyer_status_mapping --buyer badboys \\
        --map '{"voice mail": "no_answer"}'
    python manage.py set_buyer_status_mapping --buyer badboys --show
    python manage.py set_buyer_status_mapping --buyer badboys --map '...' --dry-run

Every value is validated against leadgen.canonical_status.VALUES before
anything is written, so a typo fails loudly here rather than becoming a
needs_review flag on live leads later.
"""
import json

from django.core.management.base import BaseCommand, CommandError

from leadgen import canonical_status
from leadgen.models import LeadBuyer


class Command(BaseCommand):
    help = "Merge entries into a LeadBuyer's status_mapping (buyer status string -> canonical status)."

    def add_arguments(self, parser):
        parser.add_argument('--buyer', required=True, help='LeadBuyer slug.')
        parser.add_argument('--map', dest='mapping', default='',
                            help='JSON object of {"buyer status": "canonical_status"}.')
        parser.add_argument('--show', action='store_true',
                            help='Print the effective mapping and exit.')
        parser.add_argument('--dry-run', action='store_true',
                            help='Report what would change and write nothing.')

    def handle(self, *args, **options):
        try:
            buyer = LeadBuyer.objects.get(slug=options['buyer'])
        except LeadBuyer.DoesNotExist:
            raise CommandError(f'No LeadBuyer with slug {options["buyer"]!r}.')

        if options['show'] or not options['mapping']:
            self._show(buyer)
            if not options['mapping']:
                return

        additions = self._parse(options['mapping'])
        merged = {**buyer.status_mapping, **additions}

        changed = {k: v for k, v in additions.items() if buyer.status_mapping.get(k) != v}
        if not changed:
            self.stdout.write('Nothing to do — every entry is already set to that value.')
            return

        for key, value in sorted(changed.items()):
            was = buyer.status_mapping.get(key)
            self.stdout.write(f'  {key!r}: {was!r} -> {value!r}')

        if options['dry_run']:
            self.stdout.write(self.style.WARNING('--dry-run: nothing written.'))
            return

        buyer.status_mapping = merged
        buyer.save(update_fields=['status_mapping', 'updated_at'])
        self.stdout.write(self.style.SUCCESS(
            f'{buyer.slug}: {len(changed)} entr{"y" if len(changed) == 1 else "ies"} written.'))
        self._show(buyer)

    def _parse(self, raw):
        try:
            additions = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise CommandError(f'--map is not valid JSON: {exc}')
        if not isinstance(additions, dict) or not additions:
            raise CommandError('--map must be a non-empty JSON object.')

        bad = {}
        for key, value in additions.items():
            if not isinstance(key, str) or not key.strip():
                raise CommandError(f'Mapping keys must be non-empty strings; got {key!r}.')
            if value not in canonical_status.VALUES:
                bad[key] = value
        if bad:
            raise CommandError(
                'These are not canonical statuses: '
                + ', '.join(f'{k!r} -> {v!r}' for k, v in sorted(bad.items()))
                + '\nValid values: ' + ', '.join(sorted(canonical_status.VALUES)))
        return additions

    def _show(self, buyer):
        self.stdout.write(f'{buyer.slug} own status_mapping: {json.dumps(buyer.status_mapping, indent=2)}')
        effective = json.dumps(buyer.get_effective_status_mapping(), indent=2)
        self.stdout.write(f'effective (box defaults + own): {effective}')
