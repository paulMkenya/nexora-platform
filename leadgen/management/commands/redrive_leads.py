"""Re-drive leads that a buyer never actually judged — the recovery half of
a misclassified refusal.

WHY THIS EXISTS. A capacity refusal ("no room right now") is recoverable:
leadgen.tasks retries it for ~11h and cascades it down the chain. A rejection
is terminal. When a connector reads a capacity refusal as a rejection, the
lead dies on its first attempt and NOTHING re-drives it — inject_pending_leads
only looks at STATUS_NEW leads, and a rejected lead is not new. That happened
on 2026-08-18: TrackBox's "No hubs available for this lead." was classified as
a verdict on the lead, and six leads (65, 77-81) were marked rejected without
a human at the buyer ever seeing them.

Fixing the classification stops the next one; it does nothing for the ones
already on the floor. Hence this command.

Usage:
    # what would be re-driven, and why
    python manage.py redrive_leads --reason-contains "no hubs available" --dry-run
    # the ones from that incident, by id
    python manage.py redrive_leads --ids 65,77,78,79,80,81

SAFETY. A lead is skipped, loudly, if it has any DELIVERED injection (a lead
is sold once) or any PENDING one (something is already working on it). Both
are counted in the summary rather than silently dropped — a skip here means
the operator's mental model of what failed is wrong, and that is worth
reading.
"""
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

from leadgen.models import Lead, LeadBuyer, LeadInjection
from leadgen.services import start_injection
from leadgen.tasks import resolve_buyer_for_lead

# The statuses a re-drive is FOR: the buyer said no (or we recorded a no on
# its behalf) and nothing will ever try again. STATUS_NEW is deliberately not
# here — inject_pending_leads already owns that case.
REDRIVABLE_LEAD_STATUSES = (
    Lead.STATUS_REJECTED,
    Lead.STATUS_FAILED,
    Lead.STATUS_UNROUTED,
    Lead.STATUS_EXHAUSTED,
)


class Command(BaseCommand):
    help = ('Re-inject leads whose delivery failed, selected by id or by what the buyer said. '
            'Skips anything already delivered or in flight.')

    def add_arguments(self, parser):
        parser.add_argument(
            '--ids', help='Comma-separated lead ids. Exact, and ignores --reason-contains/--since.')
        parser.add_argument(
            '--reason-contains',
            help='Select leads whose latest injection failure_reason contains this text '
                 '(case-insensitive), e.g. "no hubs available".')
        parser.add_argument(
            '--buyer', help='Force this buyer slug instead of re-resolving the routing rules.')
        parser.add_argument('--limit', type=int, default=200)
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Print what would happen and change nothing.')

    def handle(self, *args, **options):
        leads = self._select(options)
        forced_buyer = self._forced_buyer(options.get('buyer'))

        enqueued = skipped_delivered = skipped_pending = skipped_no_buyer = 0
        for lead in leads:
            statuses = set(lead.injections.values_list('status', flat=True))
            if LeadInjection.STATUS_DELIVERED in statuses:
                skipped_delivered += 1
                self.stdout.write(f'  lead {lead.pk}: SKIP — already delivered to a buyer.')
                continue
            if LeadInjection.STATUS_PENDING in statuses:
                skipped_pending += 1
                self.stdout.write(f'  lead {lead.pk}: SKIP — an injection is still in flight.')
                continue

            buyer = forced_buyer or resolve_buyer_for_lead(lead)
            if buyer is None:
                skipped_no_buyer += 1
                self.stdout.write(f'  lead {lead.pk}: SKIP — no buyer resolves for this lead.')
                continue

            if options['dry_run']:
                self.stdout.write(f'  lead {lead.pk}: would re-drive to {buyer.name}.')
            else:
                # Clear the stale verdict BEFORE re-injecting. Nothing else
                # does: inject_lead_task only writes Lead.status when it
                # reaches an OUTCOME, so a re-driven lead keeps saying
                # `rejected` for the whole retry window — hours, now that a
                # capacity refusal retries on CAPACITY_RETRY_BACKOFFS. The
                # affiliate polling GET /api/leads would read a verdict that
                # no buyer is standing behind any more, which is the exact
                # misreport this whole incident was about.
                #
                # STATUS_NEW, not a new state: "nothing has judged this lead"
                # is precisely what new means. It cannot be double-enqueued
                # by inject_pending_leads either — that excludes leads with a
                # PENDING injection, and start_injection has just made one.
                Lead.objects.filter(pk=lead.pk).touch(status=Lead.STATUS_NEW)
                start_injection(lead, buyer, synchronous=False)
                self.stdout.write(f'  lead {lead.pk}: queued for {buyer.name}.')
            enqueued += 1

        verb = 'Would re-drive' if options['dry_run'] else 'Re-drove'
        self.stdout.write(self.style.SUCCESS(
            f'{verb} {enqueued} lead(s). Skipped: {skipped_delivered} already delivered, '
            f'{skipped_pending} in flight, {skipped_no_buyer} with no buyer.'
        ))

    def _select(self, options):
        """The leads to consider, newest last so the output reads in the
        order the leads arrived."""
        ids, reason = options.get('ids'), options.get('reason_contains')
        if not ids and not reason:
            raise CommandError(
                'Pass --ids or --reason-contains. This command re-sends leads to a buyer; '
                'it will not guess which ones you meant.')

        qs = Lead.objects.all()
        if ids:
            try:
                wanted = [int(part) for part in ids.split(',') if part.strip()]
            except ValueError:
                raise CommandError(f'--ids must be comma-separated integers, got: {ids!r}')
            qs = qs.filter(pk__in=wanted)
        else:
            # Deliberately matched against the FAILED injections rather than
            # the latest one: a lead whose last attempt failed for another
            # reason entirely can still carry the refusal being swept for.
            qs = qs.filter(
                Q(status__in=REDRIVABLE_LEAD_STATUSES),
                injections__status=LeadInjection.STATUS_FAILED,
                injections__failure_reason__icontains=reason,
            ).distinct()
        return list(qs.order_by('created_at')[:options['limit']])

    def _forced_buyer(self, slug):
        if not slug:
            return None
        try:
            return LeadBuyer.objects.get(slug=slug)
        except LeadBuyer.DoesNotExist:
            raise CommandError(f'No buyer with slug {slug!r}.')
