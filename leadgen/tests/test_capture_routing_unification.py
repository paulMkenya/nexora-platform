"""Tests for the capture path resolving its buyer through RoutingRules
(leadgen.tasks.resolve_buyer_for_lead -> leadgen.routing.resolve_buyer_chain).

The behaviour these pin down is what lets ONE brand run two buyers in
parallel — one traffic source to one buyer, another source to another — which
the pre-unification capture path could not express at all: it took
LeadBuyer.objects.filter(brand, is_active).first(), so under
LeadBuyer.Meta.ordering ('name',) every lead in a brand went to whichever
active buyer sorted first by name.

The regression that motivated this file is in
TestTwoSourcesInParallel::test_activating_an_alphabetically_earlier_buyer_
does_not_steal_the_other_sources_traffic — merely making a second buyer
active used to silently divert an existing partner's live traffic onto it.
"""
from unittest.mock import patch

import pytest

from brands.models import Brand
from django.contrib.auth import get_user_model

from leadgen.models import Lead, LeadBuyer, LeadInjection, RoutingRule
from leadgen.tasks import maybe_auto_inject, resolve_buyer_for_lead

User = get_user_model()


def _lead(brand=None, **kwargs):
    defaults = dict(intake_channel=Lead.CHANNEL_AFFILIATE_API,
                    email='cap@test.com', phone='+15551234567')
    defaults.update(kwargs)
    return Lead.objects.create(brand=brand, **defaults)


def _rule(brand, buyer, **kwargs):
    defaults = dict(priority=100, is_active=True)
    defaults.update(kwargs)
    return RoutingRule.objects.create(brand=brand, buyer=buyer, **defaults)


def _buyer(brand, name, slug, box_type, **kwargs):
    defaults = dict(is_active=True, auto_inject=False, base_url=f'https://{slug}.test')
    defaults.update(kwargs)
    return LeadBuyer.objects.create(brand=brand, box_type=box_type, name=name, slug=slug, **defaults)


@pytest.fixture
def second_buyer(db, brand, box_type):
    """Deliberately named so it sorts BEFORE the `buyer` fixture's 'Test
    Buyer' — 'Alpha Buyer' < 'Test Buyer'. Every test that uses this is
    asserting something the old name-ordered .first() would have got wrong."""
    return _buyer(brand, 'Alpha Buyer', 'alpha-buyer', box_type)


@pytest.mark.django_db
class TestBrandWithoutRulesKeepsLegacyBehaviour:
    """The migration guarantee: a brand nobody has written a rule for must
    deliver exactly as it always did, not go dark."""

    def test_no_rules_at_all_falls_back_to_alphabetical_pick(self, brand, buyer, second_buyer):
        assert RoutingRule.objects.filter(brand=brand).count() == 0
        assert resolve_buyer_for_lead(_lead(brand=brand)) == second_buyer  # 'Alpha' < 'Test'

    def test_an_inactive_rule_does_not_count_as_having_rules(self, brand, buyer, second_buyer):
        _rule(brand, buyer, is_active=False)
        # Still the legacy pick — an inert rule must not switch the brand's
        # regime, or flipping is_active off would silently strand every lead.
        assert resolve_buyer_for_lead(_lead(brand=brand)) == second_buyer

    def test_a_rule_pointing_at_an_inactive_buyer_does_not_count(self, brand, buyer, second_buyer):
        second_buyer.is_active = False
        second_buyer.save(update_fields=['is_active'])
        _rule(brand, second_buyer)
        # The only rule is unusable, so the brand is still effectively
        # rule-less and must keep delivering to its one active buyer.
        assert resolve_buyer_for_lead(_lead(brand=brand)) == buyer


@pytest.mark.django_db
class TestBrandWithRulesIsGovernedEntirelyByThem:
    def test_chain_head_wins_over_the_alphabetical_pick(self, brand, buyer, second_buyer):
        _rule(brand, buyer)  # wildcard -> 'Test Buyer', NOT the alphabetically first
        assert resolve_buyer_for_lead(_lead(brand=brand)) == buyer

    def test_lead_matching_no_rule_is_unrouted_not_fallen_back(self, brand, buyer, second_buyer):
        """The load-bearing half of the all-or-nothing design. A per-lead
        fallback would re-introduce the name-ordered pick for exactly the
        leads the rule set forgot — the failure mode the whole change exists
        to remove."""
        _rule(brand, buyer, country_iso2='BR')
        lead = _lead(brand=brand, country_iso2='RO')  # matches nothing
        assert resolve_buyer_for_lead(lead) is None

    def test_priority_orders_the_chain_head(self, brand, buyer, second_buyer):
        _rule(brand, second_buyer, priority=100)
        _rule(brand, buyer, priority=10)
        assert resolve_buyer_for_lead(_lead(brand=brand)) == buyer

    def test_narrow_rule_beats_wildcard_when_given_a_better_priority(self, brand, buyer, second_buyer):
        _rule(brand, buyer, priority=100)                       # brand default
        _rule(brand, second_buyer, priority=10, country_iso2='BR')  # narrow override
        assert resolve_buyer_for_lead(_lead(brand=brand, country_iso2='BR')) == second_buyer
        assert resolve_buyer_for_lead(_lead(brand=brand, country_iso2='RO')) == buyer

    def test_rules_never_cross_the_brand_boundary(self, brand, buyer, box_type):
        other = Brand.objects.create(
            slug='cap-other', name='Other', primary_domain='cap-other.test',
            tracking_domain='t.cap-other.test')
        _rule(brand, buyer)  # a wildcard rule, but for a DIFFERENT brand
        assert resolve_buyer_for_lead(_lead(brand=other)) is None


@pytest.mark.django_db
class TestTwoSourcesInParallel:
    """The scenario this change was built for: one brand, two affiliates,
    two buyers, each source pinned to its own buyer."""

    @pytest.fixture
    def sources(self, db, brand, buyer, second_buyer):
        aff_a = User.objects.create_user(username='cap_aff_a', password='x', email='a@cap.test')
        aff_b = User.objects.create_user(username='cap_aff_b', password='x', email='b@cap.test')
        # Explicit source -> buyer mapping, one rule per source.
        _rule(brand, second_buyer, priority=10, affiliate=aff_a)
        _rule(brand, buyer, priority=10, affiliate=aff_b)
        return aff_a, aff_b

    def test_each_source_reaches_its_own_buyer(self, brand, buyer, second_buyer, sources):
        aff_a, aff_b = sources
        assert resolve_buyer_for_lead(_lead(brand=brand, affiliate=aff_a)) == second_buyer
        assert resolve_buyer_for_lead(_lead(brand=brand, affiliate=aff_b)) == buyer

    def test_activating_an_alphabetically_earlier_buyer_does_not_steal_the_other_sources_traffic(
            self, brand, buyer, second_buyer, sources):
        """Turning a buyer ON must never move traffic that belongs to a
        different source. Under the old .first()-by-name selection, making
        'Alpha Buyer' active silently diverted EVERY lead in the brand onto
        it, including the ones already being delivered to 'Test Buyer'."""
        aff_a, aff_b = sources
        second_buyer.is_active = False
        second_buyer.save(update_fields=['is_active'])
        assert resolve_buyer_for_lead(_lead(brand=brand, affiliate=aff_b)) == buyer

        second_buyer.is_active = True  # the flip that used to be destructive
        second_buyer.save(update_fields=['is_active'])
        assert resolve_buyer_for_lead(_lead(brand=brand, affiliate=aff_b)) == buyer
        assert resolve_buyer_for_lead(_lead(brand=brand, affiliate=aff_a)) == second_buyer

    def test_wildcard_covers_a_source_with_no_rule_of_its_own(self, brand, buyer, second_buyer, sources):
        _rule(brand, buyer, priority=100)  # brand default, no criteria
        assert resolve_buyer_for_lead(_lead(brand=brand, affiliate=None)) == buyer


@pytest.mark.django_db
class TestMaybeAutoInjectHonoursRules:
    def test_injects_to_the_rule_selected_buyer(self, brand, buyer, second_buyer):
        _rule(brand, buyer)
        buyer.auto_inject = True
        buyer.save(update_fields=['auto_inject'])
        lead = _lead(brand=brand)
        with patch('leadgen.tasks.inject_lead_task.delay'):
            injection = maybe_auto_inject(lead)
        assert injection is not None
        assert injection.buyer == buyer

    def test_auto_inject_kill_switch_still_gates_the_rule_selected_buyer(self, brand, buyer, second_buyer):
        """A rule names the destination; auto_inject decides whether capture
        may send there on its own. The rule must not bypass the switch."""
        _rule(brand, buyer)
        assert buyer.auto_inject is False
        lead = _lead(brand=brand)
        assert maybe_auto_inject(lead) is None
        assert LeadInjection.objects.count() == 0
        lead.refresh_from_db()
        assert lead.status == Lead.STATUS_NEW  # waiting, not unrouted

    def test_no_matching_rule_marks_the_lead_unrouted(self, brand, buyer, second_buyer):
        _rule(brand, buyer, country_iso2='BR')
        lead = _lead(brand=brand, country_iso2='RO')
        assert maybe_auto_inject(lead) is None
        lead.refresh_from_db()
        assert lead.status == Lead.STATUS_UNROUTED
