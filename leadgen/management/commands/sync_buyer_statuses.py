"""Run the buyer status pull on demand, instead of waiting for Celery Beat.

Written for the Hypernet backfill: status sync was inert for that box until
HypernetConnector.fetch_lead_statuses existed (supports_status_sync was False,
so the beat task returned before it ever called a connector), which means every
lead delivered before that point has a status on the buyer's side that we never
recorded. The beat task would eventually pick them up on its own — it pulls ALL
delivered injections, not just recent ones — but "eventually" is not something
you want to guess at while confirming a fix, and a backfill you can watch is
worth more than one you infer from a log line.

Nothing here is Hypernet-specific: it is the same code path Beat runs, exposed
with a buyer filter and a preview.

    # what WOULD change, no writes
    python manage.py sync_buyer_statuses --buyer hypernet-desperados --dry-run

    # do it
    python manage.py sync_buyer_statuses --buyer hypernet-desperados

    # every active buyer (what Beat does each tick)
    python manage.py sync_buyer_statuses
"""
from django.core.management.base import BaseCommand, CommandError

from leadgen.connectors import LeadBuyerError, get_connector
from leadgen.models import LeadBuyer, LeadInjection
from leadgen.tasks import sync_buyer_statuses_for_buyer


class Command(BaseCommand):
    help = 'Pull buyer-side lead statuses now (backfill or spot-check).'

    def add_arguments(self, parser):
        parser.add_argument('--buyer', help='LeadBuyer slug. Omit for every active buyer.')
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Fetch and print what would change; write nothing.')

    def handle(self, *args, **options):
        if options['buyer']:
            buyers = list(LeadBuyer.objects.filter(slug=options['buyer']))
            if not buyers:
                raise CommandError(f'No LeadBuyer with slug {options["buyer"]!r}.')
        else:
            buyers = list(LeadBuyer.objects.filter(is_active=True))
            if not buyers:
                raise CommandError('No active LeadBuyer rows.')

        for buyer in buyers:
            self.stdout.write(f'\n=== {buyer.slug} ({buyer.name}) ===')
            connector = get_connector(buyer)
            if not connector.supports_status_sync:
                self.stdout.write(self.style.WARNING(
                    f'  {type(connector).__name__} does not support status sync — skipped. '
                    'Its leads deliver but their status never updates.'))
                continue
            if options['dry_run']:
                self._preview(buyer, connector)
            else:
                self._apply(buyer)

    def _preview(self, buyer, connector):
        """Same fetch + parse the task uses, without the write path."""
        external_ids = list(
            LeadInjection.objects.filter(buyer=buyer, status=LeadInjection.STATUS_DELIVERED)
            .exclude(external_id='').values_list('external_id', flat=True))
        if not external_ids:
            self.stdout.write('  No delivered injections with an external_id. Nothing to pull.')
            return

        self.stdout.write(f'  {len(external_ids)} delivered injection(s) to look up.')
        try:
            response = connector.fetch_lead_statuses(external_ids)
        except LeadBuyerError as exc:
            self.stderr.write(self.style.ERROR(f'  fetch failed: {exc}'))
            return

        results = connector.parse_status_sync_results(response)
        self.stdout.write(f'  buyer returned {len(results)} matching row(s):')
        for r in results:
            deposit = self.style.SUCCESS('DEPOSIT') if r['deposit'] else '       '
            # An empty updated_at is expected on this box for anything that is
            # not a deposit — their rows carry no general updated-at field. See
            # HypernetConnector.parse_status_sync_results.
            when = r['updated_at'] or '(no timestamp available)'
            self.stdout.write(
                f'    {deposit} {r["external_id"]}  status={r["buyer_status"]!r}  '
                f'{when}  geo={r["country_iso2"] or "-"}')
        absent = len(external_ids) - len(results)
        if absent:
            self.stdout.write(self.style.WARNING(
                f'  {absent} delivered lead(s) the buyer has no record of — see the '
                'connector log line and docs/hypernet-status-endpoint.md.'))
        self.stdout.write(self.style.WARNING('  DRY RUN — nothing written.'))

    def _apply(self, buyer):
        try:
            updated = sync_buyer_statuses_for_buyer(buyer)
        except Exception as exc:  # noqa: BLE001 — one buyer must not stop the rest
            self.stderr.write(self.style.ERROR(f'  failed: {exc.__class__.__name__}: {exc}'))
            return
        self.stdout.write(self.style.SUCCESS(f'  {updated} lead(s) updated.'))
