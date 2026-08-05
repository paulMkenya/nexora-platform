"""LeadBuyers are fully brand-scoped — Paul's ruling of 2026-08-05.

A LeadBuyer belongs to exactly one Brand. Each brand routes only to its own
buyers, authors its own rules, and owns the payout relationship. There are no
shared/platform buyers and no brand=None fallback.

The interesting tests here are the ones that deliberately MISCONFIGURE routing
— a rule of brand A pointing at a buyer of brand B — and prove the lead still
cannot cross. That is defended in three independent layers, and each is tested
on its own, so removing any one of them fails a test rather than silently
narrowing the guarantee to the layers that remain:

  1. RoutingRule.clean()                 — rejects the rule on save
  2. routing.resolve_buyer_chain()       — re-filters on buyer__brand
  3. services.start_injection()          — refuses at the wire

Layer 1 alone is not enough: a rule written by raw SQL, a fixture or a shell
never passes through model validation.
"""
import pytest
from django.core.exceptions import ValidationError

from brands.models import Brand
from leadgen.models import BoxType, Lead, LeadBuyer, LeadInjection, RoutingRule
from leadgen.routing import resolve_buyer_chain
from leadgen.services import start_injection
from leadgen.tasks import resolve_buyer_for_lead


@pytest.fixture
def two_brands(db):
    a = Brand.objects.create(
        name='Alpha', slug='buyer-scope-a', primary_domain='alpha.example',
        tracking_domain='t.alpha.example', is_default=True)
    b = Brand.objects.create(
        name='Beta', slug='buyer-scope-b', primary_domain='beta.example',
        tracking_domain='t.beta.example', is_default=False)
    return a, b


@pytest.fixture
def box(db):
    return BoxType.objects.create(
        name='Scope Box', slug='scope-box',
        connector_class='leadgen.connectors.LeadBuyerConnector',
        auth_type=BoxType.AUTH_API_KEY_QUERY, auth_param_name='apiKey',
        single_endpoint_path='/leads')


def _buyer(brand, box, name):
    return LeadBuyer.objects.create(
        name=name, slug=name.lower().replace(' ', '-'), brand=brand, box_type=box,
        base_url='https://buyer.test', is_active=True)


def _lead(brand, email='scope@test.com'):
    return Lead.objects.create(
        brand=brand, intake_channel=Lead.CHANNEL_LANDING_PAGE,
        email=email, phone='+15551234567')


@pytest.mark.django_db
class TestResolveBuyerForLead:
    def test_resolves_only_the_leads_own_brand(self, two_brands, box):
        brand_a, brand_b = two_brands
        buyer_a = _buyer(brand_a, box, 'Buyer A')
        _buyer(brand_b, box, 'Buyer B')
        assert resolve_buyer_for_lead(_lead(brand_a)) == buyer_a

    def test_no_buyer_in_own_brand_returns_none_not_another_brands(self, two_brands, box):
        """The removed fallback: brand B has a perfectly good active buyer,
        and a brand-A lead must still get nothing rather than borrow it.
        Pending is recoverable; delivering to the wrong counterparty is not."""
        brand_a, brand_b = two_brands
        _buyer(brand_b, box, 'Buyer B')
        assert resolve_buyer_for_lead(_lead(brand_a)) is None

    def test_lead_without_a_brand_resolves_to_nothing(self, two_brands, box):
        brand_a, _ = two_brands
        _buyer(brand_a, box, 'Buyer A')
        assert resolve_buyer_for_lead(_lead(None)) is None


@pytest.mark.django_db
class TestCrossBrandRuleCannotDeliver:
    """A rule of brand A pointing at a buyer of brand B — the misconfiguration
    Paul asked about explicitly."""

    def test_layer1_validation_rejects_the_rule(self, two_brands, box):
        brand_a, brand_b = two_brands
        foreign_buyer = _buyer(brand_b, box, 'Buyer B')
        rule = RoutingRule(brand=brand_a, buyer=foreign_buyer, name='bad', is_active=True)
        with pytest.raises(ValidationError) as exc:
            rule.full_clean()
        assert 'buyer' in exc.value.message_dict

    def test_layer2_resolver_ignores_a_rule_that_evaded_validation(self, two_brands, box):
        """Saved with .save() directly — no full_clean() — exactly as raw SQL,
        a fixture or a shell would do it."""
        brand_a, brand_b = two_brands
        own_buyer = _buyer(brand_a, box, 'Buyer A')
        foreign_buyer = _buyer(brand_b, box, 'Buyer B')
        RoutingRule.objects.create(
            brand=brand_a, buyer=foreign_buyer, name='smuggled', priority=1, is_active=True)
        RoutingRule.objects.create(
            brand=brand_a, buyer=own_buyer, name='legit', priority=2, is_active=True)

        chain = resolve_buyer_chain(_lead(brand_a))
        assert foreign_buyer not in chain, 'cross-brand buyer reached the chain'
        assert chain == [own_buyer]

    def test_layer3_injection_refuses_at_the_wire(self, two_brands, box):
        brand_a, brand_b = two_brands
        foreign_buyer = _buyer(brand_b, box, 'Buyer B')
        lead = _lead(brand_a)
        with pytest.raises(ValueError, match='Cross-brand injection refused'):
            start_injection(lead, foreign_buyer, synchronous=False)
        assert not LeadInjection.objects.filter(lead=lead).exists(), \
            'an injection row was created for a refused cross-brand delivery'

    def test_a_rule_pointing_at_its_own_brands_buyer_is_fine(self, two_brands, box):
        """The guard must not break the ordinary case."""
        brand_a, _ = two_brands
        own_buyer = _buyer(brand_a, box, 'Buyer A')
        rule = RoutingRule(brand=brand_a, buyer=own_buyer, name='good', is_active=True)
        rule.full_clean()  # must not raise
        rule.save()
        assert resolve_buyer_chain(_lead(brand_a)) == [own_buyer]


@pytest.mark.django_db
class TestNoBuyerIsVisibleNotSilent:
    """A lead with no resolvable buyer must be findable, not stuck in `new`.

    Before this, maybe_auto_inject returned None and left the lead in `new` —
    indistinguishable from one still waiting its turn, absent from the
    console's unrouted view, and invisible to a reconcile poll because nothing
    moved updated_at. failover.advance_chain already marked this exact
    condition UNROUTED; the two intake paths disagreeing was a quiet way to
    lose leads."""

    def test_lead_with_no_buyer_in_its_brand_is_marked_unrouted(self, two_brands, box):
        from leadgen.tasks import maybe_auto_inject

        brand_a, brand_b = two_brands
        _buyer(brand_b, box, 'Other Brand Buyer')   # exists, but not brand A's
        lead = _lead(brand_a)

        assert maybe_auto_inject(lead) is None
        lead.refresh_from_db()
        assert lead.status == Lead.STATUS_UNROUTED

    def test_being_marked_unrouted_moves_updated_at(self, two_brands, box):
        """So a reconcile poll actually surfaces it."""
        from leadgen.tasks import maybe_auto_inject

        brand_a, _ = two_brands
        lead = _lead(brand_a)
        before = Lead.objects.get(pk=lead.pk).updated_at

        maybe_auto_inject(lead)

        assert Lead.objects.get(pk=lead.pk).updated_at > before

    def test_a_gated_off_buyer_leaves_the_lead_in_new(self, two_brands, box):
        """auto_inject=False means "waiting", not "nowhere to go" — a
        destination exists, so UNROUTED would be a lie."""
        from leadgen.tasks import maybe_auto_inject

        brand_a, _ = two_brands
        buyer = _buyer(brand_a, box, 'Gated Buyer')
        assert buyer.auto_inject is False
        lead = _lead(brand_a)

        assert maybe_auto_inject(lead) is None
        lead.refresh_from_db()
        assert lead.status != Lead.STATUS_UNROUTED

    def test_an_already_delivered_lead_is_never_downgraded(self, two_brands, box):
        """The exclude() guard: a lead that already reached a buyer must not be
        relabelled UNROUTED by a later call."""
        from leadgen.tasks import maybe_auto_inject

        brand_a, _ = two_brands
        lead = _lead(brand_a)
        Lead.objects.filter(pk=lead.pk).touch(status=Lead.STATUS_INJECTED)
        lead.refresh_from_db()

        maybe_auto_inject(lead)
        lead.refresh_from_db()
        assert lead.status == Lead.STATUS_INJECTED
