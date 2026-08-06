"""Seed one wildcard RoutingRule per ACTIVE LeadBuyer, so the routing chain
reproduces today's implicit buyer selection exactly.

WHY THIS EXISTS — the capture path currently selects a buyer with
tasks.resolve_buyer_for_lead: LeadBuyer.objects.filter(brand, is_active)
.first(), which under LeadBuyer.Meta.ordering picks the alphabetically-first
buyer. The chain path (routing.resolve_buyer_chain) builds its ordered buyer
list purely from RoutingRules. Prod today has ZERO active RoutingRules, so
routing the capture path through the chain without seeding rules first would
resolve every lead to an empty chain and mark it UNROUTED — a full delivery
outage for every brand. These wildcard rules are the bridge: they make the
current implicit selection explicit, so the switch is a no-op.

EQUIVALENCE BY CONSTRUCTION, NOT BY LUCK — rules are created in each brand's
CURRENT selection order (LeadBuyer.Meta.ordering, i.e. by name) and all share
priority=100. resolve_buyer_chain breaks a priority tie on rule id ascending,
so creating them in name order makes chain order == today's name order for
every brand, including brands that have several active buyers. Verify with
--verify, which asserts exactly that rather than assuming it.

A wildcard rule leaves every criterion blank (offer/country/affiliate/
vertical/source_channel), so it matches every lead in its brand — which is
precisely what the current .first() selection does: it never consults a rule
at all.

Usage:
    python manage.py seed_wildcard_routing_rules                 # dry run
    python manage.py seed_wildcard_routing_rules --apply
    python manage.py seed_wildcard_routing_rules --verify        # equivalence proof
    python manage.py seed_wildcard_routing_rules --preflight     # unification gate

Idempotent: matched on (brand, buyer, wildcard-shaped, priority), so a rule
already seeded is left alone and a second run reports nothing to do.
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from leadgen.models import LeadBuyer, RoutingRule

WILDCARD_PRIORITY = 100
RULE_NAME = 'auto: wildcard (capture-path parity)'


def _wildcard_kwargs():
    """The 'matches every lead in this brand' criteria set — every optional
    criterion explicitly blank/null, mirroring RoutingRule's own wildcard
    semantics (see routing._rule_matches)."""
    return dict(offer=None, country_iso2='', affiliate=None, vertical='', source_channel='')


def _active_buyers_in_selection_order(brand_id=None):
    """Active buyers grouped by brand, each list in the brand's CURRENT
    selection order. LeadBuyer.Meta.ordering is ('name',) — that ordering IS
    today's behavior, which is the thing being reproduced, so it is relied on
    deliberately here rather than re-sorted."""
    qs = LeadBuyer.objects.filter(is_active=True).select_related('brand')
    if brand_id:
        qs = qs.filter(brand_id=brand_id)
    grouped = {}
    for buyer in qs:  # Meta.ordering applies
        grouped.setdefault(buyer.brand_id, []).append(buyer)
    return grouped


class Command(BaseCommand):
    help = 'Seed wildcard RoutingRules so the chain reproduces current buyer selection.'

    def add_arguments(self, parser):
        parser.add_argument('--brand', type=int, help='Only this brand id.')
        parser.add_argument('--apply', action='store_true', help='Actually write. Omit for a dry run.')
        parser.add_argument('--verify', action='store_true',
                            help='Prove chain selection == current .first() selection, per brand.')
        parser.add_argument('--preflight', action='store_true',
                            help='Exit non-zero if any brand has active buyers but no active rule. '
                                 'Run this as the gate before switching capture onto the chain.')

    def handle(self, *args, **options):
        if options['preflight']:
            return self._preflight()
        if options['verify']:
            return self._verify(options.get('brand'))
        return self._seed(options.get('brand'), apply=options['apply'])

    # --- seeding ---------------------------------------------------------

    @transaction.atomic
    def _seed(self, brand_id, *, apply):
        grouped = _active_buyers_in_selection_order(brand_id)
        if not grouped:
            self.stdout.write('No active buyers. Nothing to seed.')
            return

        created = existing = 0
        for bid, buyers in sorted(grouped.items()):
            for buyer in buyers:
                already = RoutingRule.objects.filter(
                    brand_id=bid, buyer=buyer, priority=WILDCARD_PRIORITY, **_wildcard_kwargs()
                ).first()
                if already:
                    existing += 1
                    self.stdout.write(
                        f'  brand {bid} / {buyer.name}: rule #{already.pk} already exists '
                        f'(active={already.is_active})')
                    continue
                created += 1
                self.stdout.write(f'  brand {bid} / {buyer.name}: WOULD CREATE wildcard rule')
                if apply:
                    RoutingRule.objects.create(
                        brand_id=bid, buyer=buyer, name=RULE_NAME,
                        priority=WILDCARD_PRIORITY,
                        # Active on creation, deliberately: an inactive rule
                        # would leave the chain empty and defeat the whole
                        # point. These rules only take effect once capture is
                        # switched onto the chain, which is a separate change.
                        is_active=True,
                        **_wildcard_kwargs(),
                    )

        if not apply:
            self.stdout.write(self.style.WARNING(
                f'\nDRY RUN — nothing written. Would create {created}, {existing} already present.'))
            return
        self.stdout.write(self.style.SUCCESS(
            f'\nCreated {created} wildcard rule(s); {existing} already present.'))

    # --- the equivalence proof -------------------------------------------

    def _verify(self, brand_id):
        """For every brand with active buyers, assert that what the CHAIN
        would select equals what the capture path selects TODAY — and that
        the full chain order matches the current selection order, so a brand
        that later gains a second buyer stays predictable."""
        from leadgen.models import Lead
        from leadgen.routing import resolve_buyer_chain
        from leadgen.tasks import resolve_buyer_for_lead

        grouped = _active_buyers_in_selection_order(brand_id)
        if not grouped:
            self.stdout.write('No active buyers; nothing to prove.')
            return

        failures = []
        for bid, buyers in sorted(grouped.items()):
            # An unsaved, criteria-free probe lead: every wildcard rule
            # matches it, so the chain it produces is the brand's baseline
            # order. Never saved — this is a pure computation.
            probe = Lead(brand_id=bid, intake_channel=Lead.CHANNEL_LANDING_PAGE,
                         email='probe@example.invalid', phone='+10000000000')

            today = resolve_buyer_for_lead(probe)
            chain = resolve_buyer_chain(probe)
            chain_first = chain[0] if chain else None

            expected_order = [b.name for b in buyers]
            chain_order = [b.name for b in chain]

            ok_first = (today.pk if today else None) == (chain_first.pk if chain_first else None)
            ok_order = chain_order == expected_order

            self.stdout.write(f'\nbrand {bid}:')
            self.stdout.write(f'  today  (.first() by name): {today.name if today else "—"}')
            self.stdout.write(f'  chain  (rule-ordered)    : {chain_first.name if chain_first else "—"}')
            self.stdout.write(f'  current order : {expected_order}')
            self.stdout.write(f'  chain order   : {chain_order}')
            if ok_first and ok_order:
                self.stdout.write(self.style.SUCCESS('  EQUIVALENT'))
            else:
                reason = []
                if not ok_first:
                    reason.append('selected buyer differs')
                if not ok_order:
                    reason.append('chain order differs from current order')
                self.stdout.write(self.style.ERROR('  NOT EQUIVALENT: ' + '; '.join(reason)))
                failures.append(bid)

        if failures:
            raise CommandError(
                f'Equivalence FAILED for brand(s) {failures}. Do NOT switch capture onto the '
                'chain — it would change which buyer receives leads.')
        self.stdout.write(self.style.SUCCESS(
            '\nEQUIVALENCE PROVEN for every brand with active buyers. '
            'Chain selection reproduces current selection exactly.'))

    # --- the unification gate --------------------------------------------

    def _preflight(self):
        """Refuse unification while any brand could resolve to an empty chain.

        This is the guard against the outage: capture must not be routed
        through resolve_buyer_chain while a brand has active buyers but no
        active rule, because every one of its leads would resolve to [] and
        be marked UNROUTED."""
        grouped = _active_buyers_in_selection_order(None)
        offenders = []
        for bid, buyers in sorted(grouped.items()):
            active_rules = RoutingRule.objects.filter(
                brand_id=bid, is_active=True, buyer__is_active=True, buyer__brand_id=bid).count()
            state = f'brand {bid}: {len(buyers)} active buyer(s), {active_rules} active rule(s)'
            if active_rules == 0:
                offenders.append(state)
                self.stdout.write(self.style.ERROR('  ' + state))
            else:
                self.stdout.write(self.style.SUCCESS('  ' + state))

        if offenders:
            raise CommandError(
                'PRE-FLIGHT FAILED — do not route capture through the chain yet:\n  '
                + '\n  '.join(offenders)
                + '\nEvery lead in these brands would resolve to an empty chain and be marked '
                  'UNROUTED. Run this command with --apply first, then --verify.')
        self.stdout.write(self.style.SUCCESS(
            '\nPRE-FLIGHT PASSED — every brand with active buyers has at least one active rule.'))
