"""Tests for TrackBoxConnector (leadgen/connectors.py) — the third box
onboarded, after op-brandy and Hypernet.

Request literals come from TrackBox's own published docs
(https://intercom.help/tigloo/en/articles/9349579-trackbox-api-documentation).
RESPONSE literals come from probing a live instance
(platform.traffixworld.com) on 2026-08-12, because their docs publish no
response schema at all — see docs/trackbox-integration.md.

No network: build_payload() and parse_injection_result() are pure, and the
transport tests mock requests.request the same way test_hypernet_connector.py
does.

THE ONE THING MOST WORTH PROVING, because getting it wrong is silent rather
than loud: this box answers HTTP 200 to EVERYTHING, including a flat refusal
of our credentials. The base connector classifies on the HTTP status line, so
without TrackBoxConnector's in-body classification a 401 reads as a success
and gets recorded against the LEAD as a rejection — burning good leads, one
per attempt, to report a configuration error. Several tests below exist only
to pin that.
"""
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from unittest.mock import MagicMock, patch

import pytest

from leadgen.connectors import (
    LeadBuyerCapacityError, LeadBuyerError, TrackBoxConnector, _first_present, _truthy,
)
from leadgen.models import BoxType, Lead, LeadBuyer, LeadInjection

# The real box's non-secret constants, as supplied by the partner. The
# api_key/username/password are deliberately fakes below — a test fixture is
# the last place a live credential should live.
AI = '2958839'
CI = '1'
GI = '843'
SO = 'exxtraffic'

TRACKBOX_FIELD_MAPPING = {
    'firstname': 'firstname',
    'lastname': 'lastname',
    'email': 'email',
    'phone': 'phone',
    'source_id': 'sub',
}

# Verbatim from the live box on 2026-08-12: a POST to /api/pull/customers with
# no x-api-key. Note the HTTP status was 200.
LIVE_AUTH_ERROR = {
    'status': False,
    'message': 'Cant Pull Data, please contact support with caseID: 631d86e1af576972472f26c55ef58edb',
    'code': 401,
}

# Verbatim from the live box: correct username/password, junk x-api-key.
LIVE_CREDENTIAL_MISMATCH = {
    'status': False,
    'message': ('User and password doesnt match, please supply support with case ID: '
                '370f19d4d6fce6542227c7e65d9b260c'),
    'code': 401,
}


@pytest.fixture
def trackbox_box_type(db):
    return BoxType.objects.create(
        name='TrackBox', slug='trackbox-test',
        connector_class='leadgen.connectors.TrackBoxConnector',
        auth_type=BoxType.AUTH_API_KEY_HEADER,
        auth_param_name='x-api-key',
        single_endpoint_path='/api/signup/procform',
        batch_endpoint_path='',
        fetch_endpoint_path='/api/pull/customers',
        deposits_endpoint_path='',
        batch_max_size=1,
        default_field_mapping=TRACKBOX_FIELD_MAPPING,
    )


@pytest.fixture
def trackbox_buyer(db, brand, trackbox_box_type):
    buyer = LeadBuyer.objects.create(
        brand=brand, box_type=trackbox_box_type,
        name='TrackBox - Traffix (test)', slug='trackbox-traffix-test',
        is_active=True, auto_inject=False,
        base_url='https://platform.traffixworld.com',
        extra_payload_fields={'ai': AI, 'ci': CI, 'gi': GI, 'so': SO, 'lg': 'EN'},
    )
    buyer.set_api_key('fake-test-key-not-the-real-one')
    buyer.set_extra_credentials({'username': 'fake-user', 'password': 'fake-pass'})
    buyer.save(update_fields=['api_key_encrypted', 'extra_credentials_encrypted'])
    return buyer


@pytest.fixture
def lead(db):
    return Lead.objects.create(
        intake_channel=Lead.CHANNEL_LANDING_PAGE,
        first_name='John', last_name='Doe',
        email='john.doe@example.com',
        phone='+14155552671',
        country_iso2='CA',
        vertical='crypto',
        source_id='click-abc-123',
        ip='203.0.113.45',
    )


def _response(payload, status_code=200):
    """A requests.Response double. Defaults to 200 because that is what this
    box returns for failures too — the whole point."""
    resp = MagicMock()
    resp.ok = 200 <= status_code < 300
    resp.status_code = status_code
    resp.content = b'{}'
    resp.json.return_value = payload
    resp.text = str(payload)
    return resp


# --- helpers ---------------------------------------------------------------

class TestUndocumentedSchemaHelpers:
    """_first_present/_truthy exist because this box's response schema is
    undocumented, so every field is read as a set of plausible spellings."""

    def test_first_present_returns_the_first_non_empty(self):
        assert _first_present({'b': 'two'}, 'a', 'b', 'c') == 'two'

    def test_first_present_prefers_earlier_keys(self):
        assert _first_present({'a': 'one', 'b': 'two'}, 'a', 'b') == 'one'

    def test_first_present_returns_none_when_nothing_matches(self):
        assert _first_present({'z': 1}, 'a', 'b') is None

    def test_false_counts_as_present(self):
        """A deposit flag of False is a real answer, not a missing one. If
        this fell through, a box that says 'no deposit' explicitly would be
        indistinguishable from one that says nothing, and the reader would
        move on to a laxer key."""
        assert _first_present({'deposit': False, 'isDeposited': True}, 'deposit', 'isDeposited') is False

    def test_zero_counts_as_present(self):
        assert _first_present({'ftd': 0}, 'ftd') == 0

    @pytest.mark.parametrize('value', [True, 1, '1', 'true', 'TRUE', 'yes', 'Y', 't'])
    def test_truthy_accepts_every_spelling_of_yes(self, value):
        assert _truthy(value) is True

    @pytest.mark.parametrize('value', [False, 0, '0', 'false', 'no', '', None, 'maybe', 'FTD'])
    def test_truthy_rejects_everything_else(self, value):
        """Unrecognised means False, deliberately: this reads a DEPOSIT flag,
        and a lead wrongly marked deposited bills an affiliate for a
        conversion that never happened."""
        assert _truthy(value) is False


# --- the 200-means-nothing problem -----------------------------------------

class TestSoftErrorsInsideAnHttp200:
    """The reason this connector class exists at all."""

    def test_live_auth_error_raises_instead_of_looking_like_success(self, trackbox_buyer):
        """The exact body the live box returned for a missing x-api-key,
        with the exact HTTP 200 it came with."""
        connector = TrackBoxConnector(trackbox_buyer)
        with patch('leadgen.connectors.requests.request', return_value=_response(LIVE_AUTH_ERROR)):
            with pytest.raises(LeadBuyerError) as excinfo:
                connector.inject_lead(Lead(email='a@b.test', phone='+14155552671'))
        assert 'authentication failed' in str(excinfo.value)

    def test_auth_failure_is_retryable_not_a_rejection(self, trackbox_buyer):
        """It must NOT be LeadBuyerRejectedError or LeadBuyerCapacityError.

        An auth failure is a property of OUR configuration, not of the lead.
        Cascading it would walk a perfectly good lead through the entire
        buyer chain — and mark it exhausted — because of a typo in a
        credential. The plain base class means 'retry with backoff', so the
        lead survives until a human fixes the key.
        """
        from leadgen.connectors import LeadBuyerRejectedError

        connector = TrackBoxConnector(trackbox_buyer)
        with patch('leadgen.connectors.requests.request',
                   return_value=_response(LIVE_CREDENTIAL_MISMATCH)):
            with pytest.raises(LeadBuyerError) as excinfo:
                connector.inject_lead(Lead(email='a@b.test', phone='+14155552671'))
        assert not isinstance(excinfo.value, LeadBuyerRejectedError)
        assert not isinstance(excinfo.value, LeadBuyerCapacityError)

    def test_capacity_wording_raises_capacity_error(self, trackbox_buyer):
        """A 'no room right now' answer must stay recoverable — see
        LeadBuyerCapacityError, and the 10 real leads its absence cost on
        another box."""
        connector = TrackBoxConnector(trackbox_buyer)
        body = {'status': False, 'message': 'No available brands for this geo', 'code': 400}
        with patch('leadgen.connectors.requests.request', return_value=_response(body)):
            with pytest.raises(LeadBuyerCapacityError):
                connector.inject_lead(Lead(email='a@b.test', phone='+14155552671'))

    def test_a_lead_level_verdict_is_not_raised(self, trackbox_buyer):
        """A verdict about THIS LEAD falls through to parse_injection_result,
        which records the buyer's own message as the failure reason. Raising
        would replace a readable operator explanation with a stack trace and
        lose the response payload."""
        connector = TrackBoxConnector(trackbox_buyer)
        body = {'status': False, 'message': 'Invalid phone number', 'code': 400}
        with patch('leadgen.connectors.requests.request', return_value=_response(body)):
            response = connector.inject_lead(Lead(email='a@b.test', phone='+14155552671'))
        assert response == body

    def test_a_successful_pull_has_no_status_key_and_is_not_an_error(self):
        """Their documented success envelope carries no `status` at all. If
        absence were treated as failure every healthy pull would look like an
        outage."""
        assert TrackBoxConnector._is_soft_error({'data': [], 'meta': {'lastPage': 1}}) is False

    def test_explicit_false_is_an_error(self):
        assert TrackBoxConnector._is_soft_error(LIVE_AUTH_ERROR) is True

    def test_explicit_true_is_not_an_error(self):
        assert TrackBoxConnector._is_soft_error({'status': True, 'data': {}}) is False


# --- auth ------------------------------------------------------------------

class TestAuthHeaders:

    def test_all_three_headers_are_sent(self, trackbox_buyer, lead):
        connector = TrackBoxConnector(trackbox_buyer)
        with patch('leadgen.connectors.requests.request',
                   return_value=_response({'status': True, 'data': {'orderid': 'X1'}})) as mock:
            connector.inject_lead(lead)
        headers = mock.call_args.kwargs['headers']
        assert headers['x-api-key'] == 'fake-test-key-not-the-real-one'
        assert headers['x-trackbox-username'] == 'fake-user'
        assert headers['x-trackbox-password'] == 'fake-pass'

    def test_missing_credentials_raise_rather_than_sending_a_half_auth_request(
            self, trackbox_buyer, lead):
        """Because the box answers 200 to a bad credential, sending anyway
        would produce an ordinary-looking body recorded against the LEAD as a
        rejection — burning a real lead to report a config error."""
        trackbox_buyer.set_extra_credentials({})
        trackbox_buyer.save(update_fields=['extra_credentials_encrypted'])
        connector = TrackBoxConnector(trackbox_buyer)
        with patch('leadgen.connectors.requests.request') as mock:
            with pytest.raises(LeadBuyerError, match='no username/password configured'):
                connector.inject_lead(lead)
        assert mock.call_count == 0

    def test_credentials_never_reach_the_audited_request_payload(self, trackbox_buyer, lead):
        payload = TrackBoxConnector(trackbox_buyer).build_payload(lead)
        flat = str(payload)
        assert 'fake-pass' not in flat
        assert 'fake-user' not in flat
        assert 'fake-test-key-not-the-real-one' not in flat

    def test_extra_credentials_survive_a_round_trip(self, trackbox_buyer):
        assert trackbox_buyer.get_extra_credentials() == {
            'username': 'fake-user', 'password': 'fake-pass'}

    def test_extra_credentials_are_not_stored_in_plaintext(self, trackbox_buyer):
        assert 'fake-pass' not in trackbox_buyer.extra_credentials_encrypted


# --- payload ---------------------------------------------------------------

class TestBuildPayload:

    def test_static_constants_reach_the_body(self, trackbox_buyer, lead):
        payload = TrackBoxConnector(trackbox_buyer).build_payload(lead)
        assert payload['ai'] == AI
        assert payload['ci'] == CI
        assert payload['gi'] == GI
        assert payload['so'] == SO
        assert payload['lg'] == 'EN'

    def test_lead_fields_are_mapped_flat(self, trackbox_buyer, lead):
        payload = TrackBoxConnector(trackbox_buyer).build_payload(lead)
        assert payload['firstname'] == 'John'
        assert payload['lastname'] == 'Doe'
        assert payload['email'] == 'john.doe@example.com'
        assert payload['sub'] == 'click-abc-123'

    def test_phone_loses_its_plus(self, trackbox_buyer, lead):
        """Their own documented example is '4407012259886' — no plus."""
        assert TrackBoxConnector(trackbox_buyer).build_payload(lead)['phone'] == '14155552671'

    def test_userip_is_sent(self, trackbox_buyer, lead):
        assert TrackBoxConnector(trackbox_buyer).build_payload(lead)['userip'] == '203.0.113.45'

    def test_password_is_redacted_in_the_audit_copy(self, trackbox_buyer, lead):
        from leadgen.connectors import REDACTED

        assert TrackBoxConnector(trackbox_buyer).build_payload(lead)['password'] == REDACTED

    def test_the_real_password_goes_on_the_wire_only(self, trackbox_buyer, lead):
        """build_payload() is what inject_lead_task audits; inject_lead() is
        what it sends. The separation is structural, not a convention."""
        from leadgen.connectors import REDACTED

        connector = TrackBoxConnector(trackbox_buyer)
        with patch('leadgen.connectors.requests.request',
                   return_value=_response({'status': True, 'data': {'orderid': 'X1'}})) as mock:
            connector.inject_lead(lead)
        sent = mock.call_args.kwargs['json']
        assert sent['password'] != REDACTED
        assert sent['password']
        assert connector.build_payload(lead)['password'] == REDACTED

    def test_a_lead_value_is_never_clobbered_by_a_static_constant(self, trackbox_buyer, lead):
        """Precedence: a mapped LEAD value always wins, so a box-level
        default can never overwrite what we know about this lead."""
        trackbox_buyer.extra_payload_fields = {**trackbox_buyer.extra_payload_fields,
                                               'email': 'box-default@example.com'}
        payload = TrackBoxConnector(trackbox_buyer).build_payload(lead)
        assert payload['email'] == 'john.doe@example.com'

    def test_build_payload_is_deterministic(self, trackbox_buyer, lead):
        """inject_lead_task calls it twice — auditing the first result while
        sending the second. If they differed the audit trail would be a
        record of something that was never sent."""
        connector = TrackBoxConnector(trackbox_buyer)
        assert connector.build_payload(lead) == connector.build_payload(lead)

    def test_batch_injection_is_refused(self, trackbox_buyer, lead):
        with pytest.raises(LeadBuyerError, match='no batch injection endpoint'):
            TrackBoxConnector(trackbox_buyer).inject_batch([lead])

    def test_posts_to_the_documented_path(self, trackbox_buyer, lead):
        connector = TrackBoxConnector(trackbox_buyer)
        with patch('leadgen.connectors.requests.request',
                   return_value=_response({'status': True, 'data': {'orderid': 'X1'}})) as mock:
            connector.inject_lead(lead)
        assert mock.call_args.args[0] == 'POST'
        assert mock.call_args.args[1] == 'https://platform.traffixworld.com/api/signup/procform'


# --- injection results -----------------------------------------------------

class TestParseInjectionResult:

    def test_success_is_delivered(self, trackbox_buyer):
        result = TrackBoxConnector(trackbox_buyer).parse_injection_result(
            {'status': True, 'data': {'orderid': 'ORD-99'}})
        assert result == ('ORD-99', 'delivered', '')

    def test_id_is_found_at_the_top_level_too(self, trackbox_buyer):
        external_id, status, _ = TrackBoxConnector(trackbox_buyer).parse_injection_result(
            {'status': True, 'orderid': 'ORD-TOP'})
        assert (external_id, status) == ('ORD-TOP', 'delivered')

    def test_id_is_found_in_a_data_list(self, trackbox_buyer):
        external_id, _, _ = TrackBoxConnector(trackbox_buyer).parse_injection_result(
            {'status': True, 'data': [{'customerid': 'C-7'}]})
        assert external_id == 'C-7'

    def test_success_with_no_recognisable_id_is_still_delivered(self, trackbox_buyer, caplog):
        """The lead WAS accepted — reporting it as failed would be a lie and
        would cascade it to a competitor. But an empty external_id excludes
        it from every future status sync, so this must be loud."""
        result = TrackBoxConnector(trackbox_buyer).parse_injection_result(
            {'status': True, 'data': {'somethingElse': 'x'}})
        assert result[1] == 'delivered'
        assert result[0] == ''
        assert 'no recognisable lead id' in caplog.text

    def test_duplicate_wording_is_classified_as_duplicate(self, trackbox_buyer):
        """'duplicate' routes to Lead.STATUS_DUPLICATE rather than a generic
        failure — a different operator question with a different answer."""
        _, status, _ = TrackBoxConnector(trackbox_buyer).parse_injection_result(
            {'status': False, 'message': 'Lead already exists', 'code': 409})
        assert status == 'duplicate'

    def test_other_failures_carry_the_buyers_own_message(self, trackbox_buyer):
        _, status, reason = TrackBoxConnector(trackbox_buyer).parse_injection_result(
            {'status': False, 'message': 'Invalid phone number', 'code': 400})
        assert status == 'failed'
        assert 'Invalid phone number' in reason

    def test_empty_body_is_not_a_success(self, trackbox_buyer):
        _, status, reason = TrackBoxConnector(trackbox_buyer).parse_injection_result({})
        assert status == 'failed'
        assert 'Empty response body' in reason


# --- audit sanitization ----------------------------------------------------

class TestAuditSanitization:
    """Their `data` object carries autologin URLs — a bearer credential that
    logs the lead straight into the broker. response_payload is rendered to
    affiliates (affiliate_ui/templates/affiliate_ui/leads.html)."""

    def test_autologin_url_is_redacted(self, trackbox_buyer):
        from leadgen.connectors import REDACTED

        raw = {'status': True, 'data': {
            'orderid': 'ORD-1',
            'autoLoginUrl': 'https://broker.example/auto?token=SECRET-BEARER',
        }}
        audited = TrackBoxConnector(trackbox_buyer).sanitize_response_for_audit(raw)
        assert audited['data']['autoLoginUrl'] == REDACTED
        assert 'SECRET-BEARER' not in str(audited)

    def test_an_unknown_autologin_key_is_redacted_too(self, trackbox_buyer):
        """The point of default-deny: their response schema is undocumented,
        so this must hold WITHOUT knowing the key's name in advance."""
        raw = {'status': True, 'data': {'someFutureLoginLink': 'https://x/?token=SECRET'}}
        audited = TrackBoxConnector(trackbox_buyer).sanitize_response_for_audit(raw)
        assert 'SECRET' not in str(audited)

    def test_the_lead_id_survives(self, trackbox_buyer):
        raw = {'status': True, 'data': {'orderid': 'ORD-1', 'autoLoginUrl': 'https://x/?t=S'}}
        audited = TrackBoxConnector(trackbox_buyer).sanitize_response_for_audit(raw)
        assert audited['data']['orderid'] == 'ORD-1'

    def test_the_failure_message_survives(self, trackbox_buyer):
        """On a failure their message is the only operator-readable
        explanation, and carries the support caseID a human needs."""
        audited = TrackBoxConnector(trackbox_buyer).sanitize_response_for_audit(LIVE_AUTH_ERROR)
        assert 'caseID' in audited['message']
        assert audited['code'] == 401


# --- status sync -----------------------------------------------------------

@pytest.fixture
def delivered_injection(db, trackbox_buyer, lead):
    injection = LeadInjection.objects.create(
        lead=lead, buyer=trackbox_buyer, status=LeadInjection.STATUS_DELIVERED,
        external_id='ORD-99',
    )
    LeadInjection.objects.filter(pk=injection.pk).update(
        created_at=datetime(2026, 8, 10, 12, 0, tzinfo=dt_timezone.utc))
    return injection


class TestStatusSync:

    def test_pull_is_a_post_with_a_json_body(self, trackbox_buyer, delivered_injection):
        """Their pull endpoint is POST-with-a-body, not the base class's GET
        with a query string. Sent as query params the box would ignore the
        window entirely."""
        connector = TrackBoxConnector(trackbox_buyer)
        with patch('leadgen.connectors.requests.request',
                   return_value=_response({'data': [], 'meta': {'lastPage': 1}})) as mock:
            connector.fetch_lead_statuses(['ORD-99'])
        assert mock.call_args.args[0] == 'POST'
        assert mock.call_args.args[1] == 'https://platform.traffixworld.com/api/pull/customers'
        body = mock.call_args.kwargs['json']
        assert body['type'] == '3'
        assert 'from' in body and 'to' in body

    def test_window_uses_their_datetime_format(self, trackbox_buyer, delivered_injection):
        connector = TrackBoxConnector(trackbox_buyer)
        with patch('leadgen.connectors.requests.request',
                   return_value=_response({'data': [], 'meta': {'lastPage': 1}})) as mock:
            connector.fetch_lead_statuses(['ORD-99'])
        body = mock.call_args.kwargs['json']
        # 'YYYY-MM-DD HH:MM:SS', no timezone marker
        datetime.strptime(body['from'], '%Y-%m-%d %H:%M:%S')
        datetime.strptime(body['to'], '%Y-%m-%d %H:%M:%S')

    def test_window_is_built_from_the_injection_date(self, trackbox_buyer, delivered_injection):
        """Their from/to filter on REGISTRATION date, not on when a status
        changed — so windowing on 'the last hour of changes' would silently
        miss almost every deposit. The window must bracket 2026-08-10."""
        connector = TrackBoxConnector(trackbox_buyer)
        with patch('leadgen.connectors.requests.request',
                   return_value=_response({'data': [], 'meta': {'lastPage': 1}})) as mock:
            connector.fetch_lead_statuses(['ORD-99'])
        body = mock.call_args.kwargs['json']
        start = datetime.strptime(body['from'], '%Y-%m-%d %H:%M:%S')
        end = datetime.strptime(body['to'], '%Y-%m-%d %H:%M:%S')
        injected = datetime(2026, 8, 10, 12, 0)
        assert start < injected < end
        assert injected - start >= timedelta(hours=48)

    def test_rows_are_narrowed_to_the_requested_ids(self, trackbox_buyer, delivered_injection):
        connector = TrackBoxConnector(trackbox_buyer)
        body = {'data': [{'orderid': 'ORD-99', 'status': 'new'},
                         {'orderid': 'SOMEONE-ELSE', 'status': 'ftd'}],
                'meta': {'lastPage': 1}}
        with patch('leadgen.connectors.requests.request', return_value=_response(body)):
            response = connector.fetch_lead_statuses(['ORD-99'])
        assert response['count'] == 1
        assert response['data'][0]['orderid'] == 'ORD-99'

    def test_pages_until_last_page(self, trackbox_buyer, delivered_injection):
        connector = TrackBoxConnector(trackbox_buyer)
        pages = [
            _response({'data': [{'orderid': 'OTHER'}], 'meta': {'currentPage': 1, 'lastPage': 2}}),
            _response({'data': [{'orderid': 'ORD-99'}], 'meta': {'currentPage': 2, 'lastPage': 2}}),
        ]
        with patch('leadgen.connectors.requests.request', side_effect=pages) as mock:
            response = connector.fetch_lead_statuses(['ORD-99'])
        assert mock.call_count == 2
        assert response['count'] == 1

    def test_pagination_is_bounded(self, trackbox_buyer, delivered_injection):
        """A box claiming an ever-receding lastPage must not spin a worker
        forever."""
        connector = TrackBoxConnector(trackbox_buyer)
        forever = _response({'data': [{'orderid': 'X'}], 'meta': {'lastPage': 99999}})
        with patch('leadgen.connectors.requests.request', return_value=forever) as mock:
            connector.fetch_lead_statuses(['ORD-99'])
        assert mock.call_count == TrackBoxConnector.STATUS_SYNC_MAX_PAGES

    def test_an_error_body_during_a_pull_raises_rather_than_reading_as_empty(
            self, trackbox_buyer, delivered_injection):
        """THE SILENT-OUTAGE GUARD. This box answers 200 to failures, so
        treating an error body as 'no rows' would report an auth outage as
        'nothing changed' and the sync would log as perfectly healthy while
        delivering no statuses at all."""
        connector = TrackBoxConnector(trackbox_buyer)
        with patch('leadgen.connectors.requests.request', return_value=_response(LIVE_AUTH_ERROR)):
            with pytest.raises(LeadBuyerError):
                connector.fetch_lead_statuses(['ORD-99'])

    def test_no_external_ids_makes_no_request(self, trackbox_buyer):
        connector = TrackBoxConnector(trackbox_buyer)
        with patch('leadgen.connectors.requests.request') as mock:
            assert connector.fetch_lead_statuses([]) == {'count': 0, 'data': []}
        assert mock.call_count == 0

    def test_unknown_external_ids_make_no_request(self, trackbox_buyer):
        connector = TrackBoxConnector(trackbox_buyer)
        with patch('leadgen.connectors.requests.request') as mock:
            assert connector.fetch_lead_statuses(['never-injected']) == {'count': 0, 'data': []}
        assert mock.call_count == 0

    def test_supports_status_sync_is_on(self):
        assert TrackBoxConnector.supports_status_sync is True


class TestParseStatusSyncResults:

    def test_maps_a_plausible_row(self, trackbox_buyer):
        results = TrackBoxConnector(trackbox_buyer).parse_status_sync_results(
            {'data': [{'orderid': 'ORD-1', 'status': 'no answer', 'country': 'CA'}]})
        assert results == [{
            'external_id': 'ORD-1', 'buyer_status': 'no answer',
            'deposit': False, 'updated_at': '', 'country_iso2': 'CA',
        }]

    def test_a_deposit_flag_is_read(self, trackbox_buyer):
        results = TrackBoxConnector(trackbox_buyer).parse_status_sync_results(
            {'data': [{'orderid': 'ORD-1', 'status': 'ftd', 'deposit': True,
                       'depositDate': '2026-08-11 10:00:00'}]})
        assert results[0]['deposit'] is True
        assert results[0]['updated_at'] == '2026-08-11 10:00:00'

    def test_a_deposit_status_string_counts_even_without_a_flag(self, trackbox_buyer):
        results = TrackBoxConnector(trackbox_buyer).parse_status_sync_results(
            {'data': [{'orderid': 'ORD-1', 'status': 'Deposit'}]})
        assert results[0]['deposit'] is True

    def test_an_unrecognised_row_is_not_falsely_converted(self, trackbox_buyer):
        """Reporting deposit=False for a row we cannot read leaves the lead
        visible and unconverted. The opposite error bills an affiliate for a
        conversion that never happened."""
        results = TrackBoxConnector(trackbox_buyer).parse_status_sync_results(
            {'data': [{'orderid': 'ORD-1', 'somethingNew': 'x'}]})
        assert results[0]['deposit'] is False
        assert results[0]['buyer_status'] == ''

    def test_a_row_with_no_id_is_skipped(self, trackbox_buyer):
        assert TrackBoxConnector(trackbox_buyer).parse_status_sync_results(
            {'data': [{'status': 'new'}]}) == []

    def test_empty_and_malformed_responses_are_survivable(self, trackbox_buyer):
        connector = TrackBoxConnector(trackbox_buyer)
        assert connector.parse_status_sync_results({}) == []
        assert connector.parse_status_sync_results({'data': None}) == []
        assert connector.parse_status_sync_results({'data': ['not-a-dict']}) == []


# --- registry wiring -------------------------------------------------------

class TestConnectorSelection:

    def test_get_connector_resolves_the_trackbox_class(self, trackbox_buyer):
        """BoxType.connector_class is a dotted path resolved via
        import_string — a typo here means every lead on this box silently
        goes out through the GENERIC connector, which would read a 401 as a
        success."""
        from leadgen.connectors import get_connector

        assert isinstance(get_connector(trackbox_buyer), TrackBoxConnector)

    def test_the_seed_command_points_at_a_real_class(self):
        from django.utils.module_loading import import_string

        from leadgen.management.commands.seed_trackbox_box import Command  # noqa: F401

        assert import_string('leadgen.connectors.TrackBoxConnector') is TrackBoxConnector


# --- the console/admin forms -----------------------------------------------

class TestBuyerSecretsForms:
    """BuyerSecretsFormMixin, on both forms that use it.

    These exist because the mixin's first version failed SILENTLY: written
    as a plain class, its declared fields were never collected by Django's
    form metaclass, so `api_key` disappeared from the form and the console
    quietly stopped persisting credentials while still validating, still
    saving, and still redirecting. Nothing surfaced that as an error.
    """

    def test_both_secret_fields_exist_on_the_console_form(self, db):
        from leadgen.forms import LeadBuyerForm

        fields = LeadBuyerForm().fields
        assert 'api_key' in fields
        assert 'extra_credentials' in fields

    def test_both_secret_fields_exist_on_the_admin_form(self, db):
        from leadgen.admin import LeadBuyerAdminForm

        fields = LeadBuyerAdminForm().fields
        assert 'api_key' in fields
        assert 'extra_credentials' in fields

    def test_ciphertext_columns_are_never_rendered_as_inputs(self, db):
        """A *_encrypted column left in the form renders its raw Fernet
        ciphertext in a text input, and saving writes it back as though an
        operator had typed it."""
        from leadgen.admin import LeadBuyerAdminForm
        from leadgen.forms import LeadBuyerForm

        for form in (LeadBuyerForm(), LeadBuyerAdminForm()):
            assert 'api_key_encrypted' not in form.fields
            assert 'extra_credentials_encrypted' not in form.fields

    def test_saving_persists_both_secrets(self, db, brand, trackbox_box_type):
        from leadgen.forms import LeadBuyerForm

        form = LeadBuyerForm(data={
            'brand': brand.pk, 'box_type': trackbox_box_type.pk,
            'name': 'Form Buyer', 'slug': 'form-buyer',
            'is_active': 'on', 'base_url': 'https://form.test',
            'api_key': 'the-key', 'field_mapping': '{}', 'status_mapping': '{}',
            'extra_payload_fields': '{}',
            'extra_credentials': '{"username": "u1", "password": "p1"}',
        })
        assert form.is_valid(), form.errors
        buyer = form.save()
        assert buyer.get_api_key() == 'the-key'
        assert buyer.get_extra_credentials() == {'username': 'u1', 'password': 'p1'}

    def test_blank_secrets_leave_the_stored_ones_untouched(self, db, trackbox_buyer):
        """Editing an existing buyer without retyping its secrets must not
        wipe them — the whole reason both fields are write-only-and-optional."""
        from leadgen.forms import LeadBuyerForm

        form = LeadBuyerForm(instance=trackbox_buyer, data={
            'brand': trackbox_buyer.brand_id, 'box_type': trackbox_buyer.box_type_id,
            'name': 'Renamed', 'slug': trackbox_buyer.slug,
            'is_active': 'on', 'base_url': trackbox_buyer.base_url,
            'api_key': '', 'extra_credentials': '',
            'field_mapping': '{}', 'status_mapping': '{}', 'extra_payload_fields': '{}',
        })
        assert form.is_valid(), form.errors
        buyer = form.save()
        assert buyer.get_api_key() == 'fake-test-key-not-the-real-one'
        assert buyer.get_extra_credentials() == {'username': 'fake-user', 'password': 'fake-pass'}

    @pytest.mark.parametrize('bad', ['not json', '[1, 2]', '"a string"', '42'])
    def test_non_object_extra_credentials_are_rejected(self, db, brand, trackbox_box_type, bad):
        """Caught at the form, not at injection time — otherwise a typo only
        surfaces when a real lead fails to deliver, long after the operator
        who made it has moved on."""
        from leadgen.forms import LeadBuyerForm

        form = LeadBuyerForm(data={
            'brand': brand.pk, 'box_type': trackbox_box_type.pk,
            'name': 'Bad Buyer', 'slug': 'bad-buyer',
            'is_active': 'on', 'base_url': 'https://bad.test',
            'field_mapping': '{}', 'status_mapping': '{}', 'extra_payload_fields': '{}',
            'extra_credentials': bad,
        })
        assert not form.is_valid()
        assert 'extra_credentials' in form.errors


# --- the real live response ------------------------------------------------

# VERBATIM from the first real accepted lead on the live Traffix box
# (2026-08-12), with the autologin token replaced by a placeholder and the
# customer id rewritten — both are live credentials/identifiers and a test
# fixture is the last place either belongs.
#
# Keep this literal in sync with the box, not tidy. Three things about it
# were not guessable from their documentation and each broke a first
# implementation:
#   * `data` is a STRING (the autologin URL), not an object;
#   * the lead id lives at `addonData.data`, two levels down, and NOWHERE
#     else on the response;
#   * `error` is an empty LIST on success, not null or absent.
LIVE_SUCCESS = {
    'status': True,
    'data': 'https://platform.traffixworld.com/u/d/PLACEHOLDERTOKEN',
    'error': [],
    'addonData': {
        'status': 'successful',
        'data': {
            'loginURLIsForm': False,
            'customerId': 'PLACEHOLDERCUSTOMERID',
            'uniqueid': 'PLACEHOLDERCUSTOMERID',
            'brokerUrl': 'xxx',
            'id': 'PLACEHOLDERCUSTOMERID',
            'loginURL': 'https://platform.traffixworld.com/u/d/PLACEHOLDERTOKEN',
        },
        'failLog': True,
        'fallbackURL': False,
    },
    'originalData': [],
}


class TestLiveSuccessResponse:
    """Pinned against a real accepted lead, not against a guess."""

    def test_the_lead_id_is_found_two_levels_down(self, trackbox_buyer):
        """It lives ONLY at addonData.data. Searching the top level and
        `data` alone returned empty on the first real delivery, which would
        have excluded the lead from every future status sync."""
        external_id, status, reason = TrackBoxConnector(
            trackbox_buyer).parse_injection_result(LIVE_SUCCESS)
        assert external_id == 'PLACEHOLDERCUSTOMERID'
        assert status == 'delivered'
        assert reason == ''

    def test_no_id_warning_is_not_emitted_for_a_real_success(self, trackbox_buyer, caplog):
        TrackBoxConnector(trackbox_buyer).parse_injection_result(LIVE_SUCCESS)
        assert 'no recognisable lead id' not in caplog.text


class TestAutologinUrlIsNeverAudited:
    """THE REGRESSION THIS FILE EXISTS FOR.

    `data` on a successful signup is the autologin URL as a bare STRING — a
    bearer credential that logs the lead straight into the broker's client
    area. It was originally allowlisted on the assumption it was a container
    to recurse into, and allowlisting a scalar publishes it verbatim onto
    LeadInjection.response_payload, which
    affiliate_ui/templates/affiliate_ui/leads.html renders to affiliates.

    These tests exist to stop someone "helpfully" re-trusting the key later.
    """

    def test_the_top_level_autologin_url_is_redacted(self, trackbox_buyer):
        from leadgen.connectors import REDACTED

        audited = TrackBoxConnector(trackbox_buyer).sanitize_response_for_audit(LIVE_SUCCESS)
        assert audited['data'] == REDACTED

    def test_the_nested_autologin_url_is_redacted(self, trackbox_buyer):
        from leadgen.connectors import REDACTED

        audited = TrackBoxConnector(trackbox_buyer).sanitize_response_for_audit(LIVE_SUCCESS)
        assert audited['addonData']['data']['loginURL'] == REDACTED

    def test_the_token_appears_nowhere_in_the_audit_copy(self, trackbox_buyer):
        """The whole-object assertion — the one that would have caught the
        original leak regardless of which key carried it."""
        audited = TrackBoxConnector(trackbox_buyer).sanitize_response_for_audit(LIVE_SUCCESS)
        assert 'PLACEHOLDERTOKEN' not in str(audited)

    def test_the_lead_id_still_survives_sanitization(self, trackbox_buyer):
        """Redaction must not cost the identifier an operator needs to
        reconcile a lead against the buyer's own console."""
        audited = TrackBoxConnector(trackbox_buyer).sanitize_response_for_audit(LIVE_SUCCESS)
        assert audited['addonData']['data']['customerId'] == 'PLACEHOLDERCUSTOMERID'

    def test_a_scalar_under_an_allowlisted_key_is_redacted_by_shape(self, trackbox_buyer):
        """The general rule: only a CONTAINER may be trusted to a name. A key
        that is an object today and a credential tomorrow must still be
        safe."""
        from leadgen.connectors import REDACTED

        audited = TrackBoxConnector(trackbox_buyer).sanitize_response_for_audit(
            {'status': True, 'data': 'https://broker/auto?token=LEAKED'})
        assert audited['data'] == REDACTED
        assert 'LEAKED' not in str(audited)

    def test_broker_url_and_fallback_url_never_survive(self, trackbox_buyer):
        from leadgen.connectors import REDACTED

        audited = TrackBoxConnector(trackbox_buyer).sanitize_response_for_audit(LIVE_SUCCESS)
        assert audited['addonData']['data']['brokerUrl'] == REDACTED
        assert audited['addonData']['fallbackURL'] == REDACTED
