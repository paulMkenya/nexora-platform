"""Re-run existing LeadInjection.response_payload rows through the connector's
own sanitize_response_for_audit(), so historical rows match the write-time
behavior introduced with default-deny audit sanitisation.

Why a command and not a hand-written UPDATE: the sanitisation must come from
the SAME code path that runs at write time (connectors.sanitize_response_for_
audit, via the row's own buyer/BoxType connector class), or the backfill
drifts from the live behavior the moment an allowlist changes. A literal SQL
UPDATE would encode today's allowlist as a frozen constant.

DRY RUN BY DEFAULT. Nothing is written without --apply.

Usage:
    # show what would change, network-wide
    python manage.py resanitize_injection_payloads

    # one specific row
    python manage.py resanitize_injection_payloads --id 7

    # actually write (take a dump first)
    python manage.py resanitize_injection_payloads --id 7 --apply

    # bulk write needs a second, explicit flag
    python manage.py resanitize_injection_payloads --apply --all-rows

SEQUENCING — this command cannot run on a branch that lacks
connectors.sanitize_response_for_audit(). It resolves each row's connector via
get_connector() and calls that method; on an older branch every row raises
AttributeError, including op-brandy rows (the method lives on the BASE
LeadBuyerConnector). It must therefore run AFTER the connector changes are
deployed, never standalone or against an older image.

Idempotent: a row already sanitised re-sanitises to itself, so re-running is
safe and a second pass reports zero changes.

Note this only rewrites response_payload. request_payload is left alone: it
has never contained a credential (verified against prod — the only keys ever
written are the mapped lead fields), and the Hypernet password is redacted at
build time by HypernetConnector.build_payload rather than after the fact.
"""
import json

from django.core.management.base import BaseCommand, CommandError

from leadgen.connectors import get_connector
from leadgen.models import LeadInjection


class Command(BaseCommand):
    help = 'Re-sanitise historical LeadInjection.response_payload rows (dry run unless --apply).'

    def add_arguments(self, parser):
        parser.add_argument('--id', type=int, help='Only this LeadInjection id.')
        parser.add_argument('--buyer', help='Only injections for this buyer slug.')
        parser.add_argument('--apply', action='store_true',
                            help='Actually write. Omit for a dry run.')
        parser.add_argument('--all-rows', action='store_true',
                            help='Required to --apply without --id. Guards the bulk path so a '
                                 'reflexive --apply cannot redact every audit row at once.')
        parser.add_argument('--verbose-diff', action='store_true',
                            help='Print full before/after JSON for every changed row.')

    def _connector_for(self, injection):
        """The connector for this row's buyer, or None if it can't be built.

        Returning None rather than raising keeps one unresolvable buyer from
        aborting a scan over the whole table; the caller counts it as skipped.
        Both reasons warn on stderr so a skipped row is never silent.
        """
        if injection.buyer.box_type_id is None:
            self.stderr.write(self.style.WARNING(
                f'#{injection.pk}: buyer {injection.buyer.slug!r} has no box_type; '
                'cannot resolve a connector. Skipped.'))
            return None
        try:
            return get_connector(injection.buyer)
        except Exception as exc:  # noqa: BLE001 — a bad connector_class must not abort the run
            self.stderr.write(self.style.WARNING(
                f'#{injection.pk}: could not build connector ({exc.__class__.__name__}: {exc}). Skipped.'))
            return None

    def handle(self, *args, **options):
        # Bulk guard: a single-row redaction is a considered act; rewriting
        # every audit row in the table should never be one keystroke away.
        # --id scoped runs stay one flag (--apply). Anything broader than a
        # single id — including --buyer — needs --all-rows as well.
        if options['apply'] and not options['id'] and not options['all_rows']:
            raise CommandError(
                'Refusing to --apply without --id. This would rewrite every matching '
                'LeadInjection.response_payload in the table. Re-run with --id <n> for a '
                'single row, or add --all-rows if a bulk redaction is genuinely what you want. '
                'Dry run (no --apply) is always unrestricted.')

        qs = LeadInjection.objects.select_related('buyer', 'buyer__box_type').exclude(
            response_payload={})
        if options['id']:
            qs = qs.filter(pk=options['id'])
        if options['buyer']:
            qs = qs.filter(buyer__slug=options['buyer'])

        scanned = changed = skipped = 0
        pending = []

        for injection in qs.order_by('pk'):
            scanned += 1
            connector = self._connector_for(injection)
            if connector is None:
                skipped += 1
                continue

            before = injection.response_payload
            after = connector.sanitize_response_for_audit(before)
            if after == before:
                continue

            changed += 1
            pending.append((injection.pk, after))
            self.stdout.write(
                f'#{injection.pk} (lead {injection.lead_id}, buyer {injection.buyer.slug}, '
                f'status {injection.status}) WOULD CHANGE')
            if options['verbose_diff']:
                self.stdout.write('  before: ' + json.dumps(before, sort_keys=True))
                self.stdout.write('  after:  ' + json.dumps(after, sort_keys=True))
            else:
                self.stdout.write('  redacted keys: ' + ', '.join(
                    sorted(_redacted_keys(before, after))) or '  (structure only)')

        if not options['apply']:
            self.stdout.write(self.style.WARNING(
                f'\nDRY RUN — nothing written. Scanned {scanned}, would change {changed}, '
                f'skipped {skipped}. Re-run with --apply to write.'))
            return

        for pk, after in pending:
            # Queryset .update() so ONLY response_payload is touched: no
            # save(), no other field disturbed, no signals, and created_at/
            # delivered_at stay exactly as they were. This table is an audit
            # trail (LeadInjectionAdmin marks every field readonly) — the
            # rewrite is a deliberate redaction, not an edit.
            LeadInjection.objects.filter(pk=pk).update(response_payload=after)

        self.stdout.write(self.style.SUCCESS(
            f'\nApplied. Scanned {scanned}, rewrote {changed}, skipped {skipped}.'))


def _redacted_keys(before, after, path=''):
    """Key paths whose value the sanitiser replaced — for the summary line."""
    out = set()
    if isinstance(before, dict) and isinstance(after, dict):
        for key, old in before.items():
            new = after.get(key)
            here = f'{path}.{key}' if path else key
            if new == '[redacted]' and old != '[redacted]':
                out.add(here)
            else:
                out |= _redacted_keys(old, new, here)
    elif isinstance(before, list) and isinstance(after, list):
        for old, new in zip(before, after):
            out |= _redacted_keys(old, new, f'{path}[]')
    return out
