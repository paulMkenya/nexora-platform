"""Exhaustive tests for the two-phase (testing/live) status authority engine
— Affiliate Inbound API spec §2, called out explicitly as "the highest-risk
logic here" (spec's Standing risks) with a demand to "test the go-live
moment exhaustively" and "a buyer status arriving one second before vs
after go-live must behave differently and correctly" (§2.2).

Wiring-level tests (does sync_buyer_statuses_for_buyer actually call into
this engine correctly) live in test_status_sync.py; these test status_sync.py
itself, directly, independent of the buyer-sync task."""
import pytest

from leadgen import canonical_status
from leadgen.models import AffiliateOfferLink, Lead, LeadStatusEvent
from leadgen.status_sync import (
    StatusAuthorityError, apply_status_change, go_live, map_buyer_status,
    resolve_affiliate_offer_link, revert_to_testing,
)


def _lead(**kwargs):
    defaults = dict(intake_channel=Lead.CHANNEL_AFFILIATE_API, email='auth@test.com', phone='+15551234567')
    defaults.update(kwargs)
    return Lead.objects.create(**defaults)


@pytest.mark.django_db
class TestResolveAffiliateOfferLink:
    def test_no_affiliate_returns_none(self, offer):
        lead = _lead(intake_channel=Lead.CHANNEL_LANDING_PAGE, affiliate=None, offer=offer)
        assert resolve_affiliate_offer_link(lead) is None

    def test_no_offer_returns_none(self, affiliate_user):
        lead = _lead(affiliate=affiliate_user, offer=None)
        assert resolve_affiliate_offer_link(lead) is None

    def test_first_use_creates_a_row_defaulting_to_testing(self, affiliate_user, offer):
        lead = _lead(affiliate=affiliate_user, offer=offer)
        assert not AffiliateOfferLink.objects.filter(affiliate=affiliate_user, offer=offer).exists()
        link = resolve_affiliate_offer_link(lead)
        assert link.phase == AffiliateOfferLink.PHASE_TESTING
        assert AffiliateOfferLink.objects.filter(pk=link.pk).exists()

    def test_reuses_the_existing_row_for_the_same_pair(self, affiliate_user, offer):
        lead_a = _lead(affiliate=affiliate_user, offer=offer, email='a@test.com')
        lead_b = _lead(affiliate=affiliate_user, offer=offer, email='b@test.com')
        link_a = resolve_affiliate_offer_link(lead_a)
        link_b = resolve_affiliate_offer_link(lead_b)
        assert link_a.pk == link_b.pk
        assert AffiliateOfferLink.objects.filter(affiliate=affiliate_user, offer=offer).count() == 1


@pytest.mark.django_db
class TestMapBuyerStatus:
    def test_blank_raw_status_is_not_a_review_case(self, buyer):
        canonical, needs_review = map_buyer_status(buyer, '')
        assert canonical is None
        assert needs_review is False

    def test_unmapped_raw_status_needs_review(self, buyer):
        canonical, needs_review = map_buyer_status(buyer, 'Some Unknown CRM Status')
        assert canonical is None
        assert needs_review is True

    def test_instance_status_mapping_overrides_box_type_default(self, buyer):
        buyer.box_type.default_status_mapping = {'Deposit': canonical_status.FTD}
        buyer.box_type.save(update_fields=['default_status_mapping'])
        buyer.status_mapping = {'Deposit': canonical_status.QUALIFIED_FTD}
        buyer.save(update_fields=['status_mapping'])
        canonical, needs_review = map_buyer_status(buyer, 'Deposit')
        assert canonical == canonical_status.QUALIFIED_FTD
        assert needs_review is False


@pytest.mark.django_db
class TestApplyStatusChangeNoAffiliate:
    """A lead with no affiliate (direct landing-page traffic) has nothing to
    gate against — every source always applies directly."""

    def test_operator_applies_directly(self, offer):
        lead = _lead(intake_channel=Lead.CHANNEL_LANDING_PAGE, affiliate=None, offer=offer)
        event = apply_status_change(lead, canonical_status.NEW, source=LeadStatusEvent.SOURCE_OPERATOR)
        assert event.applied is True
        assert event.phase_at_time == ''
        lead.refresh_from_db()
        assert lead.canonical_status == canonical_status.NEW

    def test_buyer_applies_directly(self, offer):
        lead = _lead(intake_channel=Lead.CHANNEL_LANDING_PAGE, affiliate=None, offer=offer)
        event = apply_status_change(lead, canonical_status.FTD, source=LeadStatusEvent.SOURCE_BUYER)
        assert event.applied is True
        lead.refresh_from_db()
        assert lead.canonical_status == canonical_status.FTD


@pytest.mark.django_db
class TestApplyStatusChangeTestingPhase:
    def test_operator_flip_applies(self, affiliate_user, offer):
        lead = _lead(affiliate=affiliate_user, offer=offer)
        event = apply_status_change(lead, canonical_status.TEST, source=LeadStatusEvent.SOURCE_OPERATOR)
        assert event.applied is True
        lead.refresh_from_db()
        assert lead.canonical_status == canonical_status.TEST

    def test_buyer_status_is_recorded_but_not_applied(self, affiliate_user, offer):
        lead = _lead(affiliate=affiliate_user, offer=offer)
        event = apply_status_change(
            lead, canonical_status.FTD, source=LeadStatusEvent.SOURCE_BUYER, raw_payload={'raw': 'Deposit'})
        assert event.applied is False
        assert event.to_status == canonical_status.FTD
        assert event.raw_payload == {'raw': 'Deposit'}
        lead.refresh_from_db()
        assert lead.canonical_status == ''  # untouched

    def test_buyer_status_is_still_fully_audited_even_though_not_applied(self, affiliate_user, offer):
        lead = _lead(affiliate=affiliate_user, offer=offer)
        apply_status_change(lead, canonical_status.FTD, source=LeadStatusEvent.SOURCE_BUYER)
        assert LeadStatusEvent.objects.filter(lead=lead, source=LeadStatusEvent.SOURCE_BUYER).count() == 1


@pytest.mark.django_db
class TestApplyStatusChangeLivePhase:
    def _live_lead(self, affiliate_user, offer):
        lead = _lead(affiliate=affiliate_user, offer=offer)
        link = AffiliateOfferLink.objects.create(affiliate=affiliate_user, offer=offer)
        go_live(link, actor=affiliate_user)
        return lead, link

    def test_buyer_status_applies(self, affiliate_user, offer):
        lead, _link = self._live_lead(affiliate_user, offer)
        event = apply_status_change(lead, canonical_status.FTD, source=LeadStatusEvent.SOURCE_BUYER)
        assert event.applied is True
        lead.refresh_from_db()
        assert lead.canonical_status == canonical_status.FTD

    def test_operator_flip_without_override_is_rejected(self, affiliate_user, offer):
        lead, _link = self._live_lead(affiliate_user, offer)
        with pytest.raises(StatusAuthorityError):
            apply_status_change(lead, canonical_status.TEST, source=LeadStatusEvent.SOURCE_OPERATOR)
        # rejection must not silently write a partial/incorrect event
        assert not LeadStatusEvent.objects.filter(lead=lead).exists()
        lead.refresh_from_db()
        assert lead.canonical_status == ''

    def test_operator_flip_with_override_reason_applies_and_is_logged(self, affiliate_user, offer):
        lead, _link = self._live_lead(affiliate_user, offer)
        event = apply_status_change(
            lead, canonical_status.APPROVED, source=LeadStatusEvent.SOURCE_OPERATOR, actor=affiliate_user,
            override_reason='Buyer CRM was down; confirmed FTD by phone with affiliate.')
        assert event.applied is True
        assert event.override_reason == 'Buyer CRM was down; confirmed FTD by phone with affiliate.'
        lead.refresh_from_db()
        assert lead.canonical_status == canonical_status.APPROVED


@pytest.mark.django_db
class TestGoLiveBoundary:
    """The spec's own explicit demand: 'a buyer status arriving one second
    before vs after go-live must behave differently and correctly.'"""

    def test_status_before_go_live_stays_unapplied_after_go_live(self, affiliate_user, offer):
        lead = _lead(affiliate=affiliate_user, offer=offer)
        link = AffiliateOfferLink.objects.create(affiliate=affiliate_user, offer=offer)

        before_event = apply_status_change(lead, canonical_status.FTD, source=LeadStatusEvent.SOURCE_BUYER)
        assert before_event.applied is False

        go_live(link, actor=affiliate_user)
        lead.refresh_from_db()
        assert lead.canonical_status == ''  # the pre-go-live buyer status never applied, even retroactively

        after_event = apply_status_change(lead, canonical_status.QUALIFIED_FTD, source=LeadStatusEvent.SOURCE_BUYER)
        assert after_event.applied is True
        lead.refresh_from_db()
        assert lead.canonical_status == canonical_status.QUALIFIED_FTD  # only the post-go-live one took effect

        events = list(LeadStatusEvent.objects.filter(lead=lead).order_by('created_at'))
        assert [e.applied for e in events] == [False, True]
        assert [e.phase_at_time for e in events] == [
            AffiliateOfferLink.PHASE_TESTING, AffiliateOfferLink.PHASE_LIVE]

    def test_go_live_records_actor_and_timestamp(self, affiliate_user, offer):
        link = AffiliateOfferLink.objects.create(affiliate=affiliate_user, offer=offer)
        assert link.phase_changed_at is None
        assert link.phase_changed_by is None
        go_live(link, actor=affiliate_user)
        link.refresh_from_db()
        assert link.phase == AffiliateOfferLink.PHASE_LIVE
        assert link.phase_changed_at is not None
        assert link.phase_changed_by_id == affiliate_user.pk

    def test_revert_to_testing_restores_operator_authority(self, affiliate_user, offer):
        lead = _lead(affiliate=affiliate_user, offer=offer)
        link = AffiliateOfferLink.objects.create(affiliate=affiliate_user, offer=offer)
        go_live(link, actor=affiliate_user)

        with pytest.raises(StatusAuthorityError):
            apply_status_change(lead, canonical_status.TEST, source=LeadStatusEvent.SOURCE_OPERATOR)

        revert_to_testing(link, actor=affiliate_user)
        link.refresh_from_db()
        assert link.phase == AffiliateOfferLink.PHASE_TESTING

        event = apply_status_change(lead, canonical_status.TEST, source=LeadStatusEvent.SOURCE_OPERATOR)
        assert event.applied is True  # operator is authoritative again


@pytest.mark.django_db
class TestApplyStatusChangeMisc:
    def test_unknown_canonical_status_raises(self, affiliate_user, offer):
        lead = _lead(affiliate=affiliate_user, offer=offer)
        with pytest.raises(ValueError):
            apply_status_change(lead, 'not_a_real_status', source=LeadStatusEvent.SOURCE_OPERATOR)

    def test_from_status_reflects_the_prior_value_at_write_time(self, affiliate_user, offer):
        lead = _lead(affiliate=affiliate_user, offer=offer)
        first = apply_status_change(lead, canonical_status.NEW, source=LeadStatusEvent.SOURCE_OPERATOR)
        assert first.from_status == ''
        second = apply_status_change(lead, canonical_status.TEST, source=LeadStatusEvent.SOURCE_OPERATOR)
        assert second.from_status == canonical_status.NEW

    def test_system_source_bypasses_authority_gating_even_when_live(self, affiliate_user, offer):
        lead = _lead(affiliate=affiliate_user, offer=offer)
        link = AffiliateOfferLink.objects.create(affiliate=affiliate_user, offer=offer)
        go_live(link, actor=affiliate_user)
        event = apply_status_change(lead, canonical_status.EXPIRED, source=LeadStatusEvent.SOURCE_SYSTEM)
        assert event.applied is True
        lead.refresh_from_db()
        assert lead.canonical_status == canonical_status.EXPIRED
