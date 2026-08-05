"""Exhaustive tests for leadgen.routing.resolve_buyer_chain — the pure
resolver at the heart of Phase 1 of the lead-distribution build. Per the
build guide: overlapping rules, no-match, wildcard vs specific precedence,
inactive rule/buyer exclusion, and brand isolation all need direct coverage
here, since this function is the one piece everything else (failover,
console, box registry) gets built on top of."""
import pytest

from leadgen.models import Lead, LeadBuyer, RoutingRule
from leadgen.routing import resolve_buyer_chain


def _lead(brand=None, **kwargs):
    defaults = dict(intake_channel=Lead.CHANNEL_LANDING_PAGE, email='route@test.com', phone='+15551234567')
    defaults.update(kwargs)
    return Lead.objects.create(brand=brand, **defaults)


def _rule(brand, buyer, **kwargs):
    defaults = dict(priority=100, is_active=True)
    defaults.update(kwargs)
    return RoutingRule.objects.create(brand=brand, buyer=buyer, **defaults)


@pytest.mark.django_db
class TestResolveBuyerChainBasics:
    def test_no_rules_returns_empty_chain(self, brand):
        lead = _lead(brand=brand)
        assert resolve_buyer_chain(lead) == []

    def test_lead_with_no_brand_returns_empty_chain(self, buyer, brand):
        lead = _lead(brand=None)
        _rule(brand, buyer)  # a matching wildcard rule exists, but for a different (real) brand
        assert resolve_buyer_chain(lead) == []

    def test_wildcard_rule_matches_any_lead(self, brand, buyer):
        lead = _lead(brand=brand, email='anyone@test.com')
        _rule(brand, buyer)  # every criterion blank
        assert resolve_buyer_chain(lead) == [buyer]

    def test_empty_chain_is_not_an_error(self, brand):
        lead = _lead(brand=brand)
        result = resolve_buyer_chain(lead)
        assert result == []
        assert isinstance(result, list)


@pytest.mark.django_db
class TestMatchCriteria:
    def test_offer_criterion_matches_exactly(self, brand, buyer, offer):
        lead = _lead(brand=brand, offer=offer)
        _rule(brand, buyer, offer=offer)
        assert resolve_buyer_chain(lead) == [buyer]

    def test_offer_criterion_rejects_different_offer(self, brand, buyer, offer):
        other_offer_lead = _lead(brand=brand, offer=None)  # lead has no offer at all
        _rule(brand, buyer, offer=offer)  # rule requires a specific offer
        assert resolve_buyer_chain(other_offer_lead) == []

    def test_country_iso2_criterion_matches_exactly(self, brand, buyer):
        lead = _lead(brand=brand, country_iso2='FR')
        _rule(brand, buyer, country_iso2='FR')
        assert resolve_buyer_chain(lead) == [buyer]

    def test_country_iso2_criterion_rejects_mismatch(self, brand, buyer):
        lead = _lead(brand=brand, country_iso2='DE')
        _rule(brand, buyer, country_iso2='FR')
        assert resolve_buyer_chain(lead) == []

    def test_affiliate_criterion_matches_exactly(self, brand, buyer, affiliate_user):
        lead = _lead(brand=brand, affiliate=affiliate_user)
        _rule(brand, buyer, affiliate=affiliate_user)
        assert resolve_buyer_chain(lead) == [buyer]

    def test_affiliate_criterion_rejects_different_affiliate(self, brand, buyer, affiliate_user):
        lead = _lead(brand=brand, affiliate=None)
        _rule(brand, buyer, affiliate=affiliate_user)
        assert resolve_buyer_chain(lead) == []

    def test_vertical_criterion_matches_exactly(self, brand, buyer):
        lead = _lead(brand=brand, vertical='crypto')
        _rule(brand, buyer, vertical='crypto')
        assert resolve_buyer_chain(lead) == [buyer]

    def test_vertical_criterion_rejects_mismatch(self, brand, buyer):
        lead = _lead(brand=brand, vertical='forex')
        _rule(brand, buyer, vertical='crypto')
        assert resolve_buyer_chain(lead) == []

    def test_source_channel_criterion_matches_exactly(self, brand, buyer):
        lead = _lead(brand=brand, intake_channel=Lead.CHANNEL_AFFILIATE_API)
        _rule(brand, buyer, source_channel=Lead.CHANNEL_AFFILIATE_API)
        assert resolve_buyer_chain(lead) == [buyer]

    def test_source_channel_criterion_rejects_mismatch(self, brand, buyer):
        lead = _lead(brand=brand, intake_channel=Lead.CHANNEL_LANDING_PAGE)
        _rule(brand, buyer, source_channel=Lead.CHANNEL_AFFILIATE_API)
        assert resolve_buyer_chain(lead) == []

    def test_all_set_criteria_must_match_and_not_just_one(self, brand, buyer):
        """A rule with two criteria set is an AND, not an OR — matching one
        and failing the other must still exclude the rule."""
        lead = _lead(brand=brand, country_iso2='FR', vertical='forex')  # country matches, vertical doesn't
        _rule(brand, buyer, country_iso2='FR', vertical='crypto')
        assert resolve_buyer_chain(lead) == []

    def test_all_set_criteria_matching_together_succeeds(self, brand, buyer):
        lead = _lead(brand=brand, country_iso2='FR', vertical='crypto')
        _rule(brand, buyer, country_iso2='FR', vertical='crypto')
        assert resolve_buyer_chain(lead) == [buyer]


@pytest.mark.django_db
class TestPriorityAndPrecedence:
    def test_lower_priority_number_tried_first(self, brand):
        buyer_a = LeadBuyer.objects.create(
            name='A', slug='route-a', is_active=True, base_url='https://a.test', brand=brand)
        buyer_b = LeadBuyer.objects.create(
            name='B', slug='route-b', is_active=True, base_url='https://b.test', brand=brand)
        lead = _lead(brand=brand)
        _rule(brand, buyer_b, priority=50)
        _rule(brand, buyer_a, priority=10)
        assert resolve_buyer_chain(lead) == [buyer_a, buyer_b]

    def test_specific_rule_can_outrank_a_wildcard_via_priority(self, brand):
        """Precedence is deliberately priority-driven, not an implicit
        'more specific criteria wins' scoring system — a wildcard rule at a
        lower priority number still gets tried before a highly-specific
        rule at a higher one. The operator controls order explicitly."""
        wildcard_buyer = LeadBuyer.objects.create(
            name='Wildcard', slug='route-wild', is_active=True, base_url='https://w.test', brand=brand)
        specific_buyer = LeadBuyer.objects.create(
            name='Specific', slug='route-specific', is_active=True, base_url='https://s.test', brand=brand)
        lead = _lead(brand=brand, country_iso2='FR', vertical='crypto')
        _rule(brand, wildcard_buyer, priority=1)  # no criteria — matches everything, tried first
        _rule(brand, specific_buyer, priority=99, country_iso2='FR', vertical='crypto')
        assert resolve_buyer_chain(lead) == [wildcard_buyer, specific_buyer]

    def test_same_priority_breaks_tie_by_id_for_determinism(self, brand, buyer):
        other = LeadBuyer.objects.create(
            name='Other', slug='route-tie', is_active=True, base_url='https://o.test', brand=brand)
        lead = _lead(brand=brand)
        rule1 = _rule(brand, buyer, priority=10)
        rule2 = _rule(brand, other, priority=10)
        result = resolve_buyer_chain(lead)
        # whichever rule has the lower id (created first) wins the tie
        expected = [buyer, other] if rule1.pk < rule2.pk else [other, buyer]
        assert result == expected


@pytest.mark.django_db
class TestDeduplication:
    def test_same_buyer_from_two_matching_rules_appears_once(self, brand, buyer):
        lead = _lead(brand=brand, country_iso2='FR')
        _rule(brand, buyer, priority=1)  # wildcard, matches
        _rule(brand, buyer, priority=2, country_iso2='FR')  # also matches, same buyer
        assert resolve_buyer_chain(lead) == [buyer]

    def test_buyer_appears_at_its_first_highest_priority_position(self, brand, buyer):
        other = LeadBuyer.objects.create(
            name='Other2', slug='route-dedup2', is_active=True, base_url='https://o2.test', brand=brand)
        lead = _lead(brand=brand)
        _rule(brand, other, priority=5)
        _rule(brand, buyer, priority=10)
        _rule(brand, buyer, priority=20)  # duplicate — buyer already in chain from priority=10
        assert resolve_buyer_chain(lead) == [other, buyer]

    def test_two_different_buyers_both_appear(self, brand, buyer):
        other = LeadBuyer.objects.create(
            name='Other3', slug='route-multi', is_active=True, base_url='https://o3.test', brand=brand)
        lead = _lead(brand=brand)
        _rule(brand, buyer, priority=1)
        _rule(brand, other, priority=2)
        assert resolve_buyer_chain(lead) == [buyer, other]


@pytest.mark.django_db
class TestExclusions:
    def test_inactive_rule_is_excluded_even_if_it_matches(self, brand, buyer):
        lead = _lead(brand=brand)
        _rule(brand, buyer, is_active=False)
        assert resolve_buyer_chain(lead) == []

    def test_inactive_buyer_is_excluded_even_if_rule_is_active(self, brand, buyer):
        buyer.is_active = False
        buyer.save(update_fields=['is_active'])
        lead = _lead(brand=brand)
        _rule(brand, buyer, is_active=True)
        assert resolve_buyer_chain(lead) == []

    def test_mix_of_active_and_inactive_only_returns_active(self, brand, buyer):
        other = LeadBuyer.objects.create(
            name='Other4', slug='route-excl', is_active=True, base_url='https://o4.test', brand=brand)
        lead = _lead(brand=brand)
        _rule(brand, buyer, priority=1, is_active=False)  # excluded
        _rule(brand, other, priority=2, is_active=True)   # included
        assert resolve_buyer_chain(lead) == [other]


@pytest.mark.django_db
class TestBrandIsolation:
    def test_rule_in_a_different_brand_never_matches(self, brand, buyer):
        from brands.models import Brand
        other_brand = Brand.objects.create(
            slug='route-other-brand', name='Other Brand',
            primary_domain='route-other.example.com', tracking_domain='t.route-other.example.com',
        )
        lead = _lead(brand=other_brand)
        _rule(brand, buyer)  # wildcard rule, but scoped to a DIFFERENT brand than the lead's
        assert resolve_buyer_chain(lead) == []

    def test_each_brand_only_sees_its_own_rules(self, brand, buyer):
        from brands.models import Brand
        other_brand = Brand.objects.create(
            slug='route-brand-b', name='Brand B',
            primary_domain='route-b.example.com', tracking_domain='t.route-b.example.com',
        )
        other_buyer = LeadBuyer.objects.create(
            name='BrandB Buyer', slug='route-brandb-buyer', is_active=True,
            base_url='https://bb.test', brand=other_brand)

        _rule(brand, buyer)
        _rule(other_brand, other_buyer)

        lead_a = _lead(brand=brand, email='a@test.com')
        lead_b = _lead(brand=other_brand, email='b@test.com')

        assert resolve_buyer_chain(lead_a) == [buyer]
        assert resolve_buyer_chain(lead_b) == [other_buyer]
