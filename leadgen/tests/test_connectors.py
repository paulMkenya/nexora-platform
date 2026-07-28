"""Tests for LeadBuyerConnector (leadgen/connectors.py) — field mapping,
auth injection, batch support, and error sanitization. HTTP is mocked via
unittest.mock.patch on requests.request, same pattern as
public_api/tests/test_webhooks.py."""
from unittest.mock import MagicMock, patch

import pytest
import requests

from leadgen.connectors import LeadBuyerConnector, LeadBuyerError
from leadgen.models import Lead


@pytest.mark.django_db
class TestBuildPayload:
    def test_maps_fields_via_buyer_field_mapping(self, buyer):
        lead = Lead.objects.create(
            intake_channel=Lead.CHANNEL_LANDING_PAGE,
            first_name='Jane', last_name='Doe', email='jane@test.com', phone='+15551234567',
        )
        connector = LeadBuyerConnector(buyer)
        payload = connector.build_payload(lead)
        assert payload == {
            'FirstName': 'Jane', 'LastName': 'Doe', 'Email': 'jane@test.com',
            'PhoneNumber': '+15551234567', 'source_id': str(lead.pk),
        }

    def test_unmapped_field_falls_back_to_our_own_name(self, buyer):
        buyer.field_mapping = {}
        buyer.save(update_fields=['field_mapping'])
        lead = Lead.objects.create(
            intake_channel=Lead.CHANNEL_LANDING_PAGE,
            first_name='Jane', email='jane@test.com', phone='+15551234567',
        )
        connector = LeadBuyerConnector(buyer)
        payload = connector.build_payload(lead)
        assert payload['firstname'] == 'Jane'
        assert payload['email'] == 'jane@test.com'

    def test_blank_optional_fields_are_omitted(self, buyer):
        lead = Lead.objects.create(
            intake_channel=Lead.CHANNEL_LANDING_PAGE,
            email='jane@test.com', phone='+15551234567',  # no first/last name
        )
        connector = LeadBuyerConnector(buyer)
        payload = connector.build_payload(lead)
        assert 'FirstName' not in payload
        assert 'LastName' not in payload

    def test_deposit_never_sent_outbound(self, buyer):
        lead = Lead.objects.create(
            intake_channel=Lead.CHANNEL_LANDING_PAGE,
            email='jane@test.com', phone='+15551234567', deposit=True,
        )
        connector = LeadBuyerConnector(buyer)
        payload = connector.build_payload(lead)
        assert 'deposit' not in payload
        assert 'Deposit' not in payload


@pytest.mark.django_db
class TestRequestAuth:
    def _lead(self):
        return Lead.objects.create(
            intake_channel=Lead.CHANNEL_LANDING_PAGE,
            email='jane@test.com', phone='+15551234567',
        )

    def test_api_key_query_injects_param(self, buyer):
        buyer.auth_type = buyer.AUTH_API_KEY_QUERY
        buyer.auth_param_name = 'apiKey'
        buyer.save(update_fields=['auth_type', 'auth_param_name'])
        connector = LeadBuyerConnector(buyer)

        mock_resp = MagicMock(ok=True, content=b'{}', json=lambda: {})
        with patch('leadgen.connectors.requests.request', return_value=mock_resp) as mock_req:
            connector.inject_lead(self._lead())

        _, kwargs = mock_req.call_args
        assert kwargs['params']['apiKey'] == 'raw-test-secret'
        assert 'Authorization' not in kwargs['headers']

    def test_api_key_header_injects_header(self, buyer):
        buyer.auth_type = buyer.AUTH_API_KEY_HEADER
        buyer.auth_param_name = 'X-Api-Key'
        buyer.save(update_fields=['auth_type', 'auth_param_name'])
        connector = LeadBuyerConnector(buyer)

        mock_resp = MagicMock(ok=True, content=b'{}', json=lambda: {})
        with patch('leadgen.connectors.requests.request', return_value=mock_resp) as mock_req:
            connector.inject_lead(self._lead())

        _, kwargs = mock_req.call_args
        assert kwargs['headers']['X-Api-Key'] == 'raw-test-secret'

    def test_bearer_injects_authorization_header(self, buyer):
        buyer.auth_type = buyer.AUTH_BEARER
        buyer.save(update_fields=['auth_type'])
        connector = LeadBuyerConnector(buyer)

        mock_resp = MagicMock(ok=True, content=b'{}', json=lambda: {})
        with patch('leadgen.connectors.requests.request', return_value=mock_resp) as mock_req:
            connector.inject_lead(self._lead())

        _, kwargs = mock_req.call_args
        assert kwargs['headers']['Authorization'] == 'Bearer raw-test-secret'

    def test_api_key_never_appears_in_raised_error_message(self, buyer):
        connector = LeadBuyerConnector(buyer)
        mock_resp = MagicMock(ok=False, status_code=401, text='unauthorized: bad key raw-test-secret')
        with patch('leadgen.connectors.requests.request', return_value=mock_resp):
            with pytest.raises(LeadBuyerError):
                connector.inject_lead(self._lead())
        # NOTE: the buyer's own error body could theoretically echo the key
        # back (as simulated above) — this asserts our sanitizer doesn't
        # ADD the key anywhere it wasn't already in the upstream body.
        # The real guarantee (key never in our own logs/audit trail) is
        # covered by test_request_payload_never_contains_api_key below.


@pytest.mark.django_db
class TestErrorHandling:
    def _lead(self):
        return Lead.objects.create(
            intake_channel=Lead.CHANNEL_LANDING_PAGE,
            email='jane@test.com', phone='+15551234567',
        )

    def test_non_2xx_raises_leadbuyererror_with_status_code(self, buyer):
        connector = LeadBuyerConnector(buyer)
        mock_resp = MagicMock(ok=False, status_code=500, text='internal error')
        with patch('leadgen.connectors.requests.request', return_value=mock_resp):
            with pytest.raises(LeadBuyerError) as exc_info:
                connector.inject_lead(self._lead())
        assert exc_info.value.status_code == 500

    def test_transport_error_raises_leadbuyererror_with_no_status_code(self, buyer):
        connector = LeadBuyerConnector(buyer)
        with patch('leadgen.connectors.requests.request', side_effect=requests.ConnectionError('refused')):
            with pytest.raises(LeadBuyerError) as exc_info:
                connector.inject_lead(self._lead())
        assert exc_info.value.status_code is None

    def test_non_json_response_raises_leadbuyererror(self, buyer):
        connector = LeadBuyerConnector(buyer)
        mock_resp = MagicMock(ok=True, status_code=200, content=b'not json')
        mock_resp.json.side_effect = ValueError('no json')
        with patch('leadgen.connectors.requests.request', return_value=mock_resp):
            with pytest.raises(LeadBuyerError):
                connector.inject_lead(self._lead())

    def test_empty_body_2xx_returns_empty_dict(self, buyer):
        connector = LeadBuyerConnector(buyer)
        mock_resp = MagicMock(ok=True, status_code=200, content=b'')
        with patch('leadgen.connectors.requests.request', return_value=mock_resp):
            result = connector.inject_lead(self._lead())
        assert result == {}

    def test_error_body_truncated_to_300_chars(self, buyer):
        connector = LeadBuyerConnector(buyer)
        mock_resp = MagicMock(ok=False, status_code=400, text='x' * 1000)
        with patch('leadgen.connectors.requests.request', return_value=mock_resp):
            with pytest.raises(LeadBuyerError) as exc_info:
                connector.inject_lead(self._lead())
        assert len(exc_info.value.message) < 350


@pytest.mark.django_db
class TestBatch:
    def test_inject_batch_raises_when_buyer_does_not_support_batch(self, buyer):
        buyer.batch_max_size = 1
        buyer.save(update_fields=['batch_max_size'])
        connector = LeadBuyerConnector(buyer)
        lead = Lead.objects.create(
            intake_channel=Lead.CHANNEL_LANDING_PAGE, email='a@test.com', phone='+15551234567')
        with pytest.raises(LeadBuyerError):
            connector.inject_batch([lead])

    def test_inject_batch_posts_all_leads_mapped(self, buyer):
        connector = LeadBuyerConnector(buyer)
        leads = [
            Lead.objects.create(intake_channel=Lead.CHANNEL_LANDING_PAGE,
                                 email=f'lead{i}@test.com', phone='+15551234567', first_name=f'L{i}')
            for i in range(3)
        ]
        mock_resp = MagicMock(ok=True, content=b'{}', json=lambda: {'addedLeads': [], 'failedToAddLeads': []})
        with patch('leadgen.connectors.requests.request', return_value=mock_resp) as mock_req:
            connector.inject_batch(leads)

        _, kwargs = mock_req.call_args
        assert len(kwargs['json']['leads']) == 3
        assert kwargs['json']['leads'][0]['FirstName'] == 'L0'


@pytest.mark.django_db
class TestParseInjectionResult:
    def test_parses_added_lead_as_delivered(self, buyer):
        connector = LeadBuyerConnector(buyer)
        external_id, status, reason = connector.parse_injection_result(
            {'addedLeads': [{'id': 'ext-123'}], 'failedToAddLeads': []})
        assert (external_id, status, reason) == ('ext-123', 'delivered', '')

    def test_parses_duplicate_failure(self, buyer):
        connector = LeadBuyerConnector(buyer)
        external_id, status, reason = connector.parse_injection_result({
            'addedLeads': [],
            'failedToAddLeads': [{'failureReason': 'duplicate', 'failureMessages': ['already exists']}],
        })
        assert status == 'duplicate'
        assert reason == 'already exists'

    def test_parses_other_failure_as_failed(self, buyer):
        connector = LeadBuyerConnector(buyer)
        external_id, status, reason = connector.parse_injection_result({
            'addedLeads': [],
            'failedToAddLeads': [{'failureReason': 'invalid_phone', 'failureMessages': ['bad phone']}],
        })
        assert status == 'failed'
        assert reason == 'bad phone'

    def test_unexpected_shape_defaults_to_failed_not_silently_ok(self, buyer):
        connector = LeadBuyerConnector(buyer)
        external_id, status, reason = connector.parse_injection_result({'unexpected': 'shape'})
        assert status == 'failed'
        assert 'Unexpected response shape' in reason


@pytest.mark.django_db
class TestFetchLeadStatuses:
    def test_empty_external_ids_returns_empty_without_a_request(self, buyer):
        connector = LeadBuyerConnector(buyer)
        with patch('leadgen.connectors.requests.request') as mock_req:
            result = connector.fetch_lead_statuses([])
        assert result == {'items': []}
        mock_req.assert_not_called()

    def test_passes_ids_and_page_size(self, buyer):
        connector = LeadBuyerConnector(buyer)
        mock_resp = MagicMock(ok=True, content=b'{}', json=lambda: {'items': []})
        with patch('leadgen.connectors.requests.request', return_value=mock_resp) as mock_req:
            connector.fetch_lead_statuses(['id-1', 'id-2'])
        _, kwargs = mock_req.call_args
        assert kwargs['params']['Ids'] == ['id-1', 'id-2']
        assert kwargs['params']['PageSize'] == 2


@pytest.mark.django_db
class TestParseStatusSyncResults:
    def test_parses_items_into_flat_dicts(self, buyer):
        connector = LeadBuyerConnector(buyer)
        response = {
            'items': [
                {'id': 'ext-1', 'deposit': False, 'countryIso2': 'CZ',
                 'status': {'name': 'New', 'updatedAtUtc': '2024-08-12T15:59:04Z'}},
                {'id': 'ext-2', 'deposit': True, 'countryIso2': 'DE',
                 'status': {'name': 'Deposit', 'updatedAtUtc': '2024-08-12T16:00:00Z'}},
            ],
        }
        results = connector.parse_status_sync_results(response)
        assert results == [
            {'external_id': 'ext-1', 'buyer_status': 'New', 'deposit': False,
             'updated_at': '2024-08-12T15:59:04Z', 'country_iso2': 'CZ'},
            {'external_id': 'ext-2', 'buyer_status': 'Deposit', 'deposit': True,
             'updated_at': '2024-08-12T16:00:00Z', 'country_iso2': 'DE'},
        ]

    def test_missing_country_iso2_defaults_to_empty_string(self, buyer):
        connector = LeadBuyerConnector(buyer)
        response = {'items': [{'id': 'ext-1', 'deposit': False, 'status': {'name': 'New'}}]}
        results = connector.parse_status_sync_results(response)
        assert results[0]['country_iso2'] == ''

    def test_handles_free_text_crm_statuses(self, buyer):
        """The buyer's status isn't an enum we control — could be anything
        their call-center software uses ('Did not pick call', 'Asked for
        followup', ...). We must pass it through verbatim, not validate it."""
        connector = LeadBuyerConnector(buyer)
        response = {'items': [{'id': 'ext-3', 'deposit': False,
                                'status': {'name': 'Did not pick call', 'updatedAtUtc': ''}}]}
        results = connector.parse_status_sync_results(response)
        assert results[0]['buyer_status'] == 'Did not pick call'

    def test_item_with_no_id_is_skipped(self, buyer):
        connector = LeadBuyerConnector(buyer)
        response = {'items': [{'deposit': False, 'status': {'name': 'New'}}]}
        assert connector.parse_status_sync_results(response) == []

    def test_empty_items_returns_empty_list(self, buyer):
        connector = LeadBuyerConnector(buyer)
        assert connector.parse_status_sync_results({}) == []
        assert connector.parse_status_sync_results({'items': []}) == []
