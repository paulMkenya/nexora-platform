"""Manually (or cron-triggered) enqueue injection for leads that don't
already have a pending/delivered injection — complements the automatic
on-create path (leadgen.tasks.maybe_auto_inject) for buyers you'd rather run
on a schedule / manual pass than fire on every single lead immediately.

Usage:
    python manage.py inject_pending_leads
    python manage.py inject_pending_leads --buyer op-brandy --limit 100
"""
from django.core.management.base import BaseCommand

from leadgen.models import Lead, LeadInjection
from leadgen.tasks import inject_lead_task, resolve_buyer_for_lead


class Command(BaseCommand):
    help = 'Enqueue injection for New leads that have no pending/delivered injection yet.'

    def add_arguments(self, parser):
        parser.add_argument('--buyer', help='Only enqueue leads that resolve to this buyer slug.')
        parser.add_argument('--limit', type=int, default=500)

    def handle(self, *args, **options):
        buyer_slug = options.get('buyer')
        limit = options['limit']

        leads = Lead.objects.filter(status=Lead.STATUS_NEW).exclude(
            injections__status__in=[LeadInjection.STATUS_PENDING, LeadInjection.STATUS_DELIVERED],
        ).order_by('created_at')[:limit]

        enqueued = 0
        skipped_no_buyer = 0
        skipped_wrong_buyer = 0
        for lead in leads:
            buyer = resolve_buyer_for_lead(lead)
            if buyer is None:
                skipped_no_buyer += 1
                continue
            if buyer_slug and buyer.slug != buyer_slug:
                skipped_wrong_buyer += 1
                continue
            injection = LeadInjection.objects.create(lead=lead, buyer=buyer)
            inject_lead_task.delay(injection.pk)
            enqueued += 1

        self.stdout.write(self.style.SUCCESS(
            f'Enqueued {enqueued} lead(s) for injection. '
            f'{skipped_no_buyer} skipped (no buyer configured), '
            f'{skipped_wrong_buyer} skipped (--buyer filter).'
        ))
