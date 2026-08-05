"""Tests for the periodic buyer-status sync (leadgen/tasks.py:
sync_buyer_statuses / sync_buyer_statuses_for_buyer). HTTP mocked at
leadgen.connectors.requests.request, same pattern as test_connectors.py /
test_tasks.py."""
from unittest.mock import MagicMock, patch

import pytest
import requests

from leadgen import canonical_status
from leadgen.models import AffiliateOfferLink, Lead, LeadBuyer, LeadInjection, LeadStatusEvent
from leadgen.status_sync import go_live
from leadgen.tasks import sync_buyer_statuses, sync_buyer_statuses_for_buyer


def _lead(**kwargs):
    defaults = dict(intake_channel=Lead.CHANNEL_LANDING_PAGE, email='sync@test.com', phone='+15551234567')
    defaults.update(kwargs)
    return Lead.objects.create(**defaults)


def _delivered_injection(lead, buyer, external_id):
    """Simulates what inject_lead_task leaves behind for a successful
    delivery — the injection AND the lead's own status both flip."""
    Lead.objects.filter(pk=lead.pk).update(status=Lead.STATUS_INJECTED)
    lead.status = Lead.STATUS_INJECTED
    return LeadInjection.objects.create(
        lead=lead, buyer=buyer, status=LeadInjection.STATUS_DELIVERED, external_id=external_id)


def _fetch_response(items):
    return MagicMock(ok=True, content=b'{}', json=lambda: {'items': items})


@pytest.mark.django_db
class TestSyncBuyerStatusesForBuyer:
    def test_no_delivered_injections_is_a_noop(self, buyer):
        with patch('leadgen.connectors.requests.request') as mock_req:
            count = sync_buyer_statuses_for_buyer(buyer)
        assert count == 0
        mock_req.assert_not_called()

    def test_updates_injection_and_lead_buyer_status(self, buyer):
        lead = _lead()
        injection = _delivered_injection(lead, buyer, 'ext-1')
        resp = _fetch_response([
            {'id': 'ext-1', 'deposit': False, 'status': {'name': 'New', 'updatedAtUtc': '2024-08-12T15:59:04Z'}},
        ])
        with patch('leadgen.connectors.requests.request', return_value=resp):
            count = sync_buyer_statuses_for_buyer(buyer)

        assert count == 1
        injection.refresh_from_db()
        lead.refresh_from_db()
        assert injection.buyer_status == 'New'
        assert injection.buyer_status_updated_at is not None
        assert lead.buyer_status == 'New'
        assert lead.deposit is False
        assert lead.status == Lead.STATUS_INJECTED  # unchanged — not a deposit yet

    def test_deposit_true_flips_lead_status_to_deposit(self, buyer):
        lead = _lead()
        _delivered_injection(lead, buyer, 'ext-2')
        resp = _fetch_response([
            {'id': 'ext-2', 'deposit': True, 'status': {'name': 'Deposit', 'updatedAtUtc': '2024-08-12T16:00:00Z'}},
        ])
        with patch('leadgen.connectors.requests.request', return_value=resp):
            sync_buyer_statuses_for_buyer(buyer)

        lead.refresh_from_db()
        assert lead.deposit is True
        assert lead.status == Lead.STATUS_DEPOSIT

    def test_arbitrary_crm_status_passed_through_verbatim(self, buyer):
        """The buyer's status is free text, not an enum we validate — could
        be 'Did not pick call', 'Asked for followup', anything their own
        call-center software uses."""
        lead = _lead()
        _delivered_injection(lead, buyer, 'ext-3')
        resp = _fetch_response([
            {'id': 'ext-3', 'deposit': False, 'status': {'name': 'Asked for followup', 'updatedAtUtc': ''}},
        ])
        with patch('leadgen.connectors.requests.request', return_value=resp):
            sync_buyer_statuses_for_buyer(buyer)

        lead.refresh_from_db()
        assert lead.buyer_status == 'Asked for followup'

    def test_only_delivered_injections_are_synced(self, buyer):
        pending_lead = _lead(email='pending@test.com')
        LeadInjection.objects.create(
            lead=pending_lead, buyer=buyer, status=LeadInjection.STATUS_PENDING, external_id='')
        failed_lead = _lead(email='failed@test.com')
        LeadInjection.objects.create(
            lead=failed_lead, buyer=buyer, status=LeadInjection.STATUS_FAILED, external_id='')

        with patch('leadgen.connectors.requests.request') as mock_req:
            count = sync_buyer_statuses_for_buyer(buyer)
        assert count == 0
        mock_req.assert_not_called()

    def test_result_for_unknown_external_id_is_ignored_not_crash(self, buyer):
        lead = _lead()
        _delivered_injection(lead, buyer, 'ext-4')
        # Buyer returns a lead we don't recognize (e.g. a stale/mismatched id)
        resp = _fetch_response([
            {'id': 'not-ours', 'deposit': False, 'status': {'name': 'New', 'updatedAtUtc': ''}},
        ])
        with patch('leadgen.connectors.requests.request', return_value=resp):
            count = sync_buyer_statuses_for_buyer(buyer)
        assert count == 0
        lead.refresh_from_db()
        assert lead.buyer_status == ''

    def test_transport_error_for_one_chunk_does_not_raise(self, buyer):
        lead = _lead()
        _delivered_injection(lead, buyer, 'ext-5')
        with patch('leadgen.connectors.requests.request', side_effect=requests.ConnectionError('boom')):
            # The connector turns a transport error into LeadBuyerError, which
            # sync_buyer_statuses_for_buyer catches per-chunk — one bad chunk
            # must not blow up the whole sync.
            count = sync_buyer_statuses_for_buyer(buyer)
        assert count == 0

    def test_backfills_country_iso2_when_blank(self, buyer):
        lead = _lead()
        assert lead.country_iso2 == ''
        _delivered_injection(lead, buyer, 'ext-geo1')
        resp = _fetch_response([
            {'id': 'ext-geo1', 'deposit': False, 'countryIso2': 'FR',
             'status': {'name': 'New', 'updatedAtUtc': ''}},
        ])
        with patch('leadgen.connectors.requests.request', return_value=resp):
            sync_buyer_statuses_for_buyer(buyer)
        lead.refresh_from_db()
        assert lead.country_iso2 == 'FR'

    def test_never_overwrites_an_existing_country_iso2(self, buyer):
        lead = _lead(country_iso2='US')
        _delivered_injection(lead, buyer, 'ext-geo2')
        resp = _fetch_response([
            {'id': 'ext-geo2', 'deposit': False, 'countryIso2': 'FR',
             'status': {'name': 'New', 'updatedAtUtc': ''}},
        ])
        with patch('leadgen.connectors.requests.request', return_value=resp):
            sync_buyer_statuses_for_buyer(buyer)
        lead.refresh_from_db()
        assert lead.country_iso2 == 'US'  # geolocate_lead / an earlier sync already won

    def test_chunks_requests_by_chunk_size(self, buyer):
        leads_and_injections = [(_lead(email=f'chunk{i}@test.com'), None) for i in range(3)]
        for i, (lead, _) in enumerate(leads_and_injections):
            _delivered_injection(lead, buyer, f'ext-c{i}')

        resp = _fetch_response([])
        with patch('leadgen.connectors.requests.request', return_value=resp) as mock_req:
            sync_buyer_statuses_for_buyer(buyer, chunk_size=2)
        # 3 injections, chunk_size=2 -> two fetch calls (2 + 1)
        assert mock_req.call_count == 2


@pytest.mark.django_db
class TestSyncBuyerStatusesCanonicalStatusIntegration:
    """Affiliate Inbound API spec §3.2/§2: sync_buyer_statuses_for_buyer maps
    the buyer's raw status through buyer.get_effective_status_mapping() and
    runs it through the two-phase authority engine — these tests cover that
    wiring specifically (the authority engine's own boundary logic is
    covered exhaustively in test_status_authority.py)."""

    def test_unmapped_buyer_status_sets_needs_review(self, buyer):
        lead = _lead()
        _delivered_injection(lead, buyer, 'ext-unmapped')
        resp = _fetch_response([
            {'id': 'ext-unmapped', 'deposit': False, 'status': {'name': 'Some New CRM Status', 'updatedAtUtc': ''}},
        ])
        with patch('leadgen.connectors.requests.request', return_value=resp):
            sync_buyer_statuses_for_buyer(buyer)
        lead.refresh_from_db()
        assert lead.canonical_status_needs_review is True
        assert lead.canonical_status == ''
        assert not LeadStatusEvent.objects.filter(lead=lead).exists()

    def test_mapped_buyer_status_applies_when_lead_has_no_affiliate(self, buyer):
        buyer.box_type.default_status_mapping = {'Deposit': canonical_status.FTD}
        buyer.box_type.save(update_fields=['default_status_mapping'])
        lead = _lead()  # no affiliate/offer — nothing to gate against
        _delivered_injection(lead, buyer, 'ext-mapped')
        resp = _fetch_response([
            {'id': 'ext-mapped', 'deposit': True, 'status': {'name': 'Deposit', 'updatedAtUtc': ''}},
        ])
        with patch('leadgen.connectors.requests.request', return_value=resp):
            sync_buyer_statuses_for_buyer(buyer)
        lead.refresh_from_db()
        assert lead.canonical_status == canonical_status.FTD
        assert lead.canonical_status_needs_review is False
        event = LeadStatusEvent.objects.get(lead=lead)
        assert event.applied is True
        assert event.source == LeadStatusEvent.SOURCE_BUYER
        assert event.phase_at_time == ''

    def test_mapped_buyer_status_recorded_not_applied_in_testing(self, buyer, affiliate_user, offer):
        buyer.box_type.default_status_mapping = {'Deposit': canonical_status.FTD}
        buyer.box_type.save(update_fields=['default_status_mapping'])
        lead = _lead(affiliate=affiliate_user, offer=offer)
        _delivered_injection(lead, buyer, 'ext-testing')
        resp = _fetch_response([
            {'id': 'ext-testing', 'deposit': True, 'status': {'name': 'Deposit', 'updatedAtUtc': ''}},
        ])
        with patch('leadgen.connectors.requests.request', return_value=resp):
            sync_buyer_statuses_for_buyer(buyer)
        lead.refresh_from_db()
        assert lead.canonical_status == ''  # NOT applied — testing phase, operator is authoritative
        event = LeadStatusEvent.objects.get(lead=lead)
        assert event.applied is False
        assert event.to_status == canonical_status.FTD
        assert event.phase_at_time == AffiliateOfferLink.PHASE_TESTING

    def test_mapped_buyer_status_applies_once_live(self, buyer, affiliate_user, offer):
        buyer.box_type.default_status_mapping = {'Deposit': canonical_status.FTD}
        buyer.box_type.save(update_fields=['default_status_mapping'])
        link = AffiliateOfferLink.objects.create(affiliate=affiliate_user, offer=offer)
        go_live(link, actor=None)
        lead = _lead(affiliate=affiliate_user, offer=offer)
        _delivered_injection(lead, buyer, 'ext-live')
        resp = _fetch_response([
            {'id': 'ext-live', 'deposit': True, 'status': {'name': 'Deposit', 'updatedAtUtc': ''}},
        ])
        with patch('leadgen.connectors.requests.request', return_value=resp):
            sync_buyer_statuses_for_buyer(buyer)
        lead.refresh_from_db()
        assert lead.canonical_status == canonical_status.FTD
        event = LeadStatusEvent.objects.get(lead=lead)
        assert event.applied is True
        assert event.phase_at_time == AffiliateOfferLink.PHASE_LIVE


@pytest.mark.django_db
class TestSyncBuyerStatusesTask:
    def test_only_active_buyers_are_synced(self, buyer):
        buyer.is_active = False
        buyer.save(update_fields=['is_active'])
        lead = _lead()
        _delivered_injection(lead, buyer, 'ext-inactive')

        with patch('leadgen.connectors.requests.request') as mock_req:
            sync_buyer_statuses()
        mock_req.assert_not_called()

    def test_one_buyer_failing_does_not_block_others(self, buyer):
        other_buyer = LeadBuyer.objects.create(
            name='Other Buyer', slug='sync-other-buyer', is_active=True,
            base_url='https://other.test', box_type=buyer.box_type, brand=buyer.brand)
        lead_a = _lead(email='buyera@test.com')
        _delivered_injection(lead_a, buyer, 'ext-a')
        lead_b = _lead(email='buyerb@test.com')
        _delivered_injection(lead_b, other_buyer, 'ext-b')

        good_resp = _fetch_response([
            {'id': 'ext-b', 'deposit': False, 'status': {'name': 'New', 'updatedAtUtc': ''}},
        ])

        def side_effect(method, url, **kwargs):
            if buyer.base_url in url:
                raise Exception('this buyer is down')
            return good_resp

        with patch('leadgen.connectors.requests.request', side_effect=side_effect):
            sync_buyer_statuses()  # must not raise despite buyer A failing

        lead_b.refresh_from_db()
        assert lead_b.buyer_status == 'New'
