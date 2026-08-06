"""Tests for HypernetConnector (leadgen/connectors.py) — the second box
onboarded after op-brandy, and the first needing its own connector_class.

Every payload/response literal here is copied from Hypernet's own Postman
collection (HTN-AFF-SDK), so these tests fail if our shape drifts from
theirs. No network: build_payload() and parse_injection_result() are pure,
and the two transport tests mock requests.request the same way
test_connectors.py does.

The three things worth actually proving, since a wrong answer to any of them
is silent rather than loud:
  * a successful injection parses as 'delivered', not as the base class's
    "Unexpected response shape" failure (the whole reason this class exists);
  * the static affc/bxc/vtc constants reach the body, and a lead value never
    gets clobbered by one;
  * build_payload() is DETERMINISTIC — inject_lead_task calls it twice and
    audits the first result while sending the second.
"""
from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest

from leadgen.connectors import (
    HypernetConnector, LeadBuyerError, _normalize_msisdn, _set_path,
)
from leadgen.models import BoxType, Lead, LeadBuyer

# --- the real box's constants, per the integration doc. The api_key is
# deliberately NOT here (a fake is used below) — a test fixture is the last
# place a live credential should live.
AFFC = 'AFF-QVZ353O80J'
BXC = 'BX-SO4CQTDSQ8UUY'
VTC = 'VT-HP8XSRMKVS6E7'

# Our field name -> Hypernet's, as dotted paths. Dots are what makes the flat
# field_mapping able to express Hypernet's nested `profile` — see _set_path().
HYPERNET_FIELD_MAPPING = {
    'firstname': 'profile.firstName',
    'lastname': 'profile.lastName',
    'email': 'profile.email',
    'phone': 'profile.phone',
    'vertical': 'funnel',
    'source_id': 'subId',
}


@pytest.fixture
def hypernet_box_type(db):
    return BoxType.objects.create(
        name='Hypernet', slug='hypernet-test',
        connector_class='leadgen.connectors.HypernetConnector',
        auth_type=BoxType.AUTH_API_KEY_HEADER,
        auth_param_name='x-api-key',
        single_endpoint_path='/api/external/integration/lead',
        batch_endpoint_path='',
        fetch_endpoint_path='/api/external/integration/lead',
        deposits_endpoint_path='',
        batch_max_size=1,
        default_field_mapping=HYPERNET_FIELD_MAPPING,
    )


@pytest.fixture
def hypernet_buyer(db, brand, hypernet_box_type):
    # A real brand, not brand=None: LeadBuyer.brand becomes required in
    # migration 0011, which would make a platform-wide buyer illegal and
    # break this fixture on rebase. `brand` comes from leadgen/tests/conftest.py.
    buyer = LeadBuyer.objects.create(
        brand=brand, box_type=hypernet_box_type,
        name='Hypernet - desperados (test)', slug='hypernet-desperados-test',
        is_active=True, auto_inject=False,
        base_url='https://desperados.hn-crm.com',
    )
    buyer.set_api_key('fake-test-key-not-the-real-one')
    buyer.save(update_fields=['api_key_encrypted'])
    # LeadBuyer.extra_payload_fields is not in the schema yet (its migration
    # is sequenced behind another in-flight one), so it is set in memory
    # here. The connector reads it via getattr, so this works identically
    # before and after the field lands — at which point this becomes an
    # ordinary create() kwarg and nothing else in this file changes.
    buyer.extra_payload_fields = {
        'affc': AFFC, 'bxc': BXC, 'vtc': VTC,
        'lang': 'en', 'landingLang': 'en',
        'landingURL': 'https://desperados.hn-crm.com/lp/crypto',
    }
    return buyer


@pytest.fixture
def buyer_on_base_connector(db, brand, hypernet_box_type):
    """A buyer on the generic LeadBuyerConnector, for asserting that
    default-deny audit sanitization covers op-brandy too — not just
    Hypernet. Reuses the box type only as a rate-limit/URL carrier; the
    connector under test is passed explicitly.

    Real brand, not brand=None — see hypernet_buyer for why."""
    return LeadBuyer.objects.create(
        brand=brand, box_type=hypernet_box_type,
        name='Base-connector buyer', slug='base-connector-buyer',
        is_active=True, auto_inject=False, base_url='https://buyer.test/api',
    )


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


class TestSetPath:
    """_set_path is what lets a FLAT field_mapping express Hypernet's nested
    profile — the base connector can only ever write a top-level key."""

    def test_dotted_key_nests(self):
        target = {}
        _set_path(target, 'profile.firstName', 'Jane')
        assert target == {'profile': {'firstName': 'Jane'}}

    def test_plain_key_is_top_level(self):
        target = {}
        _set_path(target, 'geo', 'CA')
        assert target == {'geo': 'CA'}

    def test_siblings_share_the_parent(self):
        target = {}
        _set_path(target, 'profile.firstName', 'Jane')
        _set_path(target, 'profile.lastName', 'Doe')
        assert target == {'profile': {'firstName': 'Jane', 'lastName': 'Doe'}}

    def test_non_dict_at_an_intermediate_key_is_replaced_not_crashed(self):
        target = {'profile': 'oops-a-string'}
        _set_path(target, 'profile.email', 'a@b.com')
        assert target == {'profile': {'email': 'a@b.com'}}


@pytest.mark.django_db
class TestBuildPayload:
    def test_matches_the_documented_request_shape(self, hypernet_buyer, lead):
        """The exact body shape from Hypernet's Postman example."""
        payload = HypernetConnector(hypernet_buyer).build_payload(lead)

        assert payload['affc'] == AFFC
        assert payload['bxc'] == BXC
        assert payload['vtc'] == VTC
        assert payload['profile']['firstName'] == 'John'
        assert payload['profile']['lastName'] == 'Doe'
        assert payload['profile']['email'] == 'john.doe@example.com'
        assert payload['profile']['password']
        assert payload['ip'] == '203.0.113.45'
        assert payload['funnel'] == 'crypto'
        assert payload['landingURL'] == 'https://desperados.hn-crm.com/lp/crypto'
        assert payload['geo'] == 'CA'
        assert payload['lang'] == 'en'
        assert payload['landingLang'] == 'en'
        assert payload['subId'] == 'click-abc-123'

    def test_top_level_keys_are_exactly_the_documented_set(self, hypernet_buyer, lead):
        payload = HypernetConnector(hypernet_buyer).build_payload(lead)
        assert set(payload) == {
            'affc', 'bxc', 'vtc', 'profile', 'ip', 'funnel',
            'landingURL', 'geo', 'lang', 'landingLang', 'subId',
        }

    def test_profile_keys_are_exactly_the_documented_set(self, hypernet_buyer, lead):
        payload = HypernetConnector(hypernet_buyer).build_payload(lead)
        assert set(payload['profile']) == {
            'firstName', 'lastName', 'email', 'password', 'phone',
        }

    def test_phone_is_normalized_to_a_bare_international_msisdn(self, hypernet_buyer, lead):
        """Hypernet's docs are explicit: "phone (no leading +)"."""
        payload = HypernetConnector(hypernet_buyer).build_payload(lead)
        assert payload['profile']['phone'] == '14155552671'

    def test_audited_payload_never_contains_the_real_password(self, hypernet_buyer, lead):
        """build_payload() feeds LeadInjection.request_payload. The
        credential is substituted in inject_lead() only."""
        payload = HypernetConnector(hypernet_buyer).build_payload(lead)
        assert payload['profile']['password'] == '[redacted]'

    def test_a_lead_value_is_never_clobbered_by_a_static_constant(self, hypernet_buyer, lead):
        """Static constants are box-level defaults; a mapped lead value must
        always win, or a fallback geo would overwrite what we know about
        this specific lead."""
        hypernet_buyer.extra_payload_fields = {
            **hypernet_buyer.extra_payload_fields, 'funnel': 'box-default-funnel'}
        payload = HypernetConnector(hypernet_buyer).build_payload(lead)
        assert payload['funnel'] == 'crypto'

    def test_missing_static_fields_do_not_raise(self, hypernet_buyer, lead):
        """A buyer configured before extra_payload_fields was populated (or
        before the field exists at all) still builds a payload — a
        misconfiguration should surface as Hypernet's own 4xx, not an
        AttributeError inside a Celery task."""
        hypernet_buyer.extra_payload_fields = None
        payload = HypernetConnector(hypernet_buyer).build_payload(lead)
        assert 'affc' not in payload
        assert payload['profile']['email'] == 'john.doe@example.com'

    def test_blank_lead_fields_are_omitted_not_sent_empty(self, hypernet_buyer):
        bare = Lead.objects.create(
            intake_channel=Lead.CHANNEL_LANDING_PAGE,
            email='bare@example.com', phone='+14155550000',
        )
        payload = HypernetConnector(hypernet_buyer).build_payload(bare)
        assert 'firstName' not in payload['profile']
        assert 'lastName' not in payload['profile']
        assert 'geo' not in payload
        assert 'ip' not in payload

    def test_source_id_falls_back_to_pk_like_the_base_connector(self, hypernet_buyer):
        bare = Lead.objects.create(
            intake_channel=Lead.CHANNEL_LANDING_PAGE,
            email='bare@example.com', phone='+14155550000',
        )
        payload = HypernetConnector(hypernet_buyer).build_payload(bare)
        assert payload['subId'] == str(bare.pk)

    def test_deposit_is_never_sent_outbound(self, hypernet_buyer, lead):
        lead.deposit = True
        lead.save(update_fields=['deposit'])
        payload = HypernetConnector(hypernet_buyer).build_payload(lead)
        assert 'deposit' not in payload
        assert 'deposit' not in payload['profile']


class TestNormalizeMsisdn:
    """Hypernet wants a bare international MSISDN. Lead.phone is NOT
    guaranteed E.164: leadgen.serializers._PHONE_RE is r'^\\+?[0-9]{7,15}$',
    so a national-format '0712345678' passes intake validation untouched,
    and the landing-page form applies no client-side formatting at all.

    The contract pinned here: '+' and the '00' international access code
    both mean "country code follows" and are removed; separators are
    stripped; a national-format number is NEVER given an invented country
    code — it is passed through and flagged instead.
    """

    @pytest.mark.parametrize('raw,expected,ambiguous', [
        # The three the review called out. The first two are genuinely the
        # SAME number and must converge; the third must NOT join them.
        ('+254712345678', '254712345678', False),
        ('254712345678', '254712345678', False),
        ('0712345678', '0712345678', True),
        # '00' is the ITU international access code — same meaning as '+'.
        ('00254712345678', '254712345678', False),
        # Separators an affiliate's form or an operator may leave in.
        ('+254 712 345 678', '254712345678', False),
        ('+254-712-345-678', '254712345678', False),
        ('+1 (415) 555-2671', '14155552671', False),
        ('  +14155552671  ', '14155552671', False),
        ('', '', False),
    ])
    def test_normalization_table(self, raw, expected, ambiguous):
        assert _normalize_msisdn(raw) == (expected, ambiguous)

    def test_national_and_international_forms_stay_distinct(self):
        """The failure the review was guarding against: a national number
        must not silently collapse onto an international one."""
        national, _ = _normalize_msisdn('0712345678')
        international, _ = _normalize_msisdn('+254712345678')
        assert national != international

    def test_plus_and_bare_forms_of_the_same_number_do_converge(self):
        assert _normalize_msisdn('+254712345678')[0] == _normalize_msisdn('254712345678')[0]

    def test_national_format_is_flagged_not_guessed(self):
        """We have lead.country_iso2 and could look up a dialing code, but
        deliberately do not — a wrong country code delivers a wrong number
        to a buyer who charges per lead."""
        digits, ambiguous = _normalize_msisdn('0712345678')
        assert ambiguous is True
        assert digits == '0712345678'  # unchanged, not prefixed with anything


@pytest.mark.django_db
class TestPassword:
    """Generated once, stored encrypted, never re-derived and never audited
    in plaintext."""

    def test_generated_once_then_read_back_for_the_same_lead(self, hypernet_buyer, lead):
        """Second call returns the STORED value, not a fresh one. A new
        password on every call would diverge from what the broker recorded
        and lock the lead out of its own account."""
        first = HypernetConnector(hypernet_buyer).get_or_create_password(lead)
        second = HypernetConnector(hypernet_buyer).get_or_create_password(lead)
        assert first == second
        assert len(first) >= 12

    def test_is_random_not_derived_from_the_pk(self, hypernet_buyer, lead):
        """Clearing the stored value and regenerating for the SAME lead must
        produce a DIFFERENT password. A derived one (e.g. HMAC over lead.pk)
        would reproduce the identical string — which is exactly what would
        let anyone holding SECRET_KEY recompute every lead's broker
        credential from a sequential integer."""
        first = HypernetConnector(hypernet_buyer).get_or_create_password(lead)

        Lead.objects.filter(pk=lead.pk).update(broker_password_encrypted='')
        lead.refresh_from_db()
        second = HypernetConnector(hypernet_buyer).get_or_create_password(lead)

        assert first != second, 'password appears to be derived from the lead, not random'

    def test_is_persisted_encrypted_not_in_plaintext(self, hypernet_buyer, lead):
        """The column must never hold the raw password — same posture as
        LeadBuyer.api_key_encrypted."""
        raw = HypernetConnector(hypernet_buyer).get_or_create_password(lead)
        lead.refresh_from_db()
        assert lead.broker_password_encrypted
        assert raw not in lead.broker_password_encrypted

        from nexora.crypto import decrypt_secret
        assert decrypt_secret(lead.broker_password_encrypted) == raw

    def test_writing_the_password_advances_updated_at(self, hypernet_buyer, lead):
        """Provisioning a credential is a lead mutation, so it must go
        through LeadQuerySet.touch() — a lead whose state changed without
        moving updated_at is invisible to the ?updated_since= reconcile
        poll."""
        before = lead.updated_at
        HypernetConnector(hypernet_buyer).get_or_create_password(lead)
        lead.refresh_from_db()
        assert lead.updated_at > before

    def test_stored_value_is_read_back_not_regenerated(self, hypernet_buyer, lead):
        """Simulates the post-migration Lead.broker_password_encrypted."""
        from nexora.crypto import encrypt_secret

        lead.broker_password_encrypted = encrypt_secret('known-password')
        assert HypernetConnector(hypernet_buyer).get_or_create_password(lead) == 'known-password'

    def test_undecryptable_stored_value_raises_rather_than_minting_a_new_one(
            self, hypernet_buyer, lead):
        """A SECRET_KEY rotation makes decrypt_secret return ''. Minting a
        replacement would silently diverge from what the broker stored and
        lock the lead out with no record of why."""
        lead.broker_password_encrypted = 'not-a-valid-fernet-token'
        with pytest.raises(LeadBuyerError):
            HypernetConnector(hypernet_buyer).get_or_create_password(lead)

    def test_the_wire_body_carries_the_real_password_and_the_audit_copy_does_not(
            self, hypernet_buyer, lead):
        """The whole point of splitting build_payload() from inject_lead()."""
        connector = HypernetConnector(hypernet_buyer)
        mock_resp = MagicMock(ok=True, content=b'{}', json=lambda: {'success': True, 'leadId': 'x'})

        with patch('leadgen.connectors.requests.request', return_value=mock_resp) as mock_req:
            connector.inject_lead(lead)

        sent = mock_req.call_args[1]['json']['profile']['password']
        audited = connector.build_payload(lead)['profile']['password']
        assert sent != '[redacted]'
        assert len(sent) >= 12
        assert audited == '[redacted]'

    def test_unsaved_lead_gets_an_ephemeral_password_and_persists_nothing(self, hypernet_buyer):
        """admin_views.buyer_test_connection injects an UNSAVED Lead."""
        probe = Lead(first_name='Nexora', last_name='TestConnection',
                     email='nexora-test-connection@example.invalid', phone='+10000000000')
        assert HypernetConnector(hypernet_buyer).get_or_create_password(probe)
        assert probe.pk is None


@pytest.mark.django_db
class TestParseInjectionResult:
    """The mismatch this whole class exists for: the base parser reads
    addedLeads/failedToAddLeads and would log every Hypernet success as
    "Unexpected response shape" — a 201 recorded as a failure."""

    def test_documented_success_response_parses_as_delivered(self, hypernet_buyer):
        # Verbatim from the Postman 201 example.
        response = {
            'success': True,
            'redirectUrl': 'https://desperados.hn-crm.com/autologin?token=abc123',
            'leadId': '64f1c2a9e1b2c3d4e5f6a7b8',
        }
        result = HypernetConnector(hypernet_buyer).parse_injection_result(response)
        assert result == ('64f1c2a9e1b2c3d4e5f6a7b8', 'delivered', '')

    def test_base_connector_would_have_got_this_wrong(self, hypernet_buyer):
        """Pins the actual regression risk: the same response through the
        BASE parser is a failure. If someone ever points this buyer at
        LeadBuyerConnector, this is what breaks."""
        from leadgen.connectors import LeadBuyerConnector

        response = {'success': True, 'redirectUrl': 'https://x/', 'leadId': 'abc'}
        _, base_status, base_reason = LeadBuyerConnector(hypernet_buyer).parse_injection_result(response)
        assert base_status == 'failed'
        assert 'Unexpected response shape' in base_reason

        _, our_status, _ = HypernetConnector(hypernet_buyer).parse_injection_result(response)
        assert our_status == 'delivered'

    def test_success_with_no_lead_id_still_delivered_with_blank_external_id(self, hypernet_buyer):
        result = HypernetConnector(hypernet_buyer).parse_injection_result(
            {'success': True, 'redirectUrl': 'https://x/'})
        assert result == ('', 'delivered', '')

    def test_success_false_is_failed(self, hypernet_buyer):
        _, status, reason = HypernetConnector(hypernet_buyer).parse_injection_result(
            {'success': False, 'message': 'Invalid phone number'})
        assert status == 'failed'
        assert reason == 'Invalid phone number'

    def test_error_key_is_used_when_message_is_absent(self, hypernet_buyer):
        _, status, reason = HypernetConnector(hypernet_buyer).parse_injection_result(
            {'success': False, 'error': 'bxc not found'})
        assert status == 'failed'
        assert reason == 'bxc not found'

    def test_undocumented_error_shape_is_captured_verbatim(self, hypernet_buyer):
        """Their error envelope isn't documented — capture whatever came
        back rather than reporting an empty reason."""
        _, status, reason = HypernetConnector(hypernet_buyer).parse_injection_result(
            {'success': False, 'errors': [{'field': 'profile.email'}]})
        assert status == 'failed'
        assert 'profile.email' in reason

    def test_reason_fits_leadinjection_failure_reason(self, hypernet_buyer):
        """LeadInjection.failure_reason is max_length=255 — an overlong
        reason must be truncated here, not blow up on save()."""
        _, _, reason = HypernetConnector(hypernet_buyer).parse_injection_result(
            {'success': False, 'message': 'x' * 1000})
        assert len(reason) == 255

    def test_empty_body_is_failed_not_silently_delivered(self, hypernet_buyer):
        """_request() returns {} for a 2xx with no body. Hypernet documents
        a JSON 201, so an empty body is unexplained — never a success."""
        _, status, reason = HypernetConnector(hypernet_buyer).parse_injection_result({})
        assert status == 'failed'
        assert 'Empty response' in reason

    def test_missing_success_key_is_failed(self, hypernet_buyer):
        _, status, _ = HypernetConnector(hypernet_buyer).parse_injection_result(
            {'leadId': 'abc'})
        assert status == 'failed'


@pytest.mark.django_db
class TestAuditSanitization:
    """Default-deny filtering of what reaches LeadInjection.response_payload.

    This matters more than a normal audit-hygiene test because
    response_payload is rendered to the AFFILIATE
    (affiliate_ui/templates/affiliate_ui/leads.html), not just to operators.
    """

    def test_redirect_url_does_not_survive_into_the_audit_copy(self, hypernet_buyer):
        """THE regression guard. Hypernet's redirectUrl is an autologin
        bearer credential — it logs the lead into the broker's client area.
        If someone later adds 'redirectUrl' to AUDIT_RESPONSE_ALLOWLIST to
        make it "available", this test fails and makes them justify
        persisting a credential in plaintext JSON that an affiliate can
        read off a web page. Do not fix this test by widening the
        allowlist."""
        response = {
            'success': True,
            'redirectUrl': 'https://desperados.hn-crm.com/autologin?token=SECRET-BEARER',
            'leadId': '64f1c2a9e1b2c3d4e5f6a7b8',
        }
        audited = HypernetConnector(hypernet_buyer).sanitize_response_for_audit(response)

        assert audited == {
            'success': True,
            'redirectUrl': '[redacted]',
            'leadId': '64f1c2a9e1b2c3d4e5f6a7b8',
        }
        assert 'SECRET-BEARER' not in str(audited)
        assert 'autologin' not in str(audited)

    def test_redirect_url_is_not_on_the_hypernet_allowlist(self, hypernet_buyer):
        """Belt and braces: asserts the intent directly, so the guard above
        can't be defeated by changing the response fixture instead."""
        assert 'redirectUrl' not in HypernetConnector.AUDIT_RESPONSE_ALLOWLIST

    def test_leadid_still_survives_so_status_sync_and_support_still_work(self, hypernet_buyer):
        audited = HypernetConnector(hypernet_buyer).sanitize_response_for_audit(
            {'success': True, 'redirectUrl': 'https://x/', 'leadId': 'abc'})
        assert audited['leadId'] == 'abc'

    def test_an_unanticipated_credential_shaped_key_is_redacted_by_default(self, hypernet_buyer):
        """The point of default-deny: catching what nobody predicted. If
        Hypernet starts returning a session token tomorrow, it is redacted
        without anyone having to have foreseen the key name."""
        audited = HypernetConnector(hypernet_buyer).sanitize_response_for_audit(
            {'success': True, 'leadId': 'abc', 'sessionToken': 'tok_live_xyz',
             'apiSecret': 'shhh'})
        assert audited['sessionToken'] == '[redacted]'
        assert audited['apiSecret'] == '[redacted]'
        assert 'tok_live_xyz' not in str(audited)

    def test_nested_and_listed_credentials_are_reached(self, hypernet_buyer):
        """A credential must not survive by hiding one level down."""
        audited = HypernetConnector(hypernet_buyer).sanitize_response_for_audit(
            {'success': True, 'leadId': 'abc',
             'meta': {'redirectUrl': 'https://x/?token=NOPE'},
             'sessions': [{'url': 'https://y/?token=ALSO-NOPE'}]})
        assert 'NOPE' not in str(audited)
        assert 'ALSO-NOPE' not in str(audited)

    def test_non_dict_response_audits_as_empty(self, hypernet_buyer):
        assert HypernetConnector(hypernet_buyer).sanitize_response_for_audit(None) == {}
        assert HypernetConnector(hypernet_buyer).sanitize_response_for_audit('nope') == {}

    def test_base_allowlist_keeps_op_brandy_envelope_and_result_ids(self, buyer_on_base_connector):
        """The base class covers op-brandy too. Its envelope, the delivered
        lead's id, and the failure detail all survive — those are what
        parse_injection_result() and a human debugging a rejection need."""
        from leadgen.connectors import LeadBuyerConnector

        audited = LeadBuyerConnector(buyer_on_base_connector).sanitize_response_for_audit({
            'addedLeads': [],
            'failedToAddLeads': [
                {'failureReason': 'duplicate', 'failureMessages': ['already exists']}],
        })
        assert audited == {
            'addedLeads': [],
            'failedToAddLeads': [
                {'failureReason': 'duplicate', 'failureMessages': ['already exists']}],
        }

    def test_base_allowlist_redacts_the_lead_pii_op_brandy_echoes_back(
            self, buyer_on_base_connector):
        """Pins the REAL production behavior change. This response body is
        the actual shape of the one delivered LeadInjection row in prod
        (id=7): op-brandy echoes the whole lead back inside addedLeads.

        Default-deny keeps the id and drops the echoed copy. That IS a
        change to what gets recorded — it is not a no-op — and it is the
        intended one: we already store all of this on the Lead row, and
        response_payload is affiliate-visible.
        """
        from leadgen.connectors import LeadBuyerConnector

        real_shape = {
            'addedLeads': [{
                'id': '019fa9c8-3bc8-70ba-936b-3a1a6ececc50',
                'email': 'Muhammadnoor12@gmail.com',
                'status': {'name': 'New', 'updatedAtUtc': '2026-07-28T17:31:39.8598027Z'},
                'deposit': False,
                'lastname': 'Abdullah',
                'sourceId': '4',
                'affiliate': None,
                'firstname': 'Muhammad Noor bin',
                'addedAtUtc': '2026-07-28T17:31:39.8597993Z',
                'phoneNumber': '6583475263',
                'failureReason': None,
                'failureMessages': None,
            }],
            'failedToAddLeads': [],
        }
        audited = LeadBuyerConnector(buyer_on_base_connector).sanitize_response_for_audit(real_shape)
        added = audited['addedLeads'][0]

        # Kept: the external id parse_injection_result() depends on.
        assert added['id'] == '019fa9c8-3bc8-70ba-936b-3a1a6ececc50'
        assert added['failureReason'] is None
        assert added['failureMessages'] is None
        # Dropped: the echoed consumer PII.
        for pii_key in ('email', 'lastname', 'firstname', 'phoneNumber'):
            assert added[pii_key] == '[redacted]'
        assert 'Muhammadnoor12@gmail.com' not in str(audited)
        assert '6583475263' not in str(audited)


@pytest.mark.django_db
class TestRedirectUrlStorage:
    """Hypernet's redirectUrl is a 3-minute, single-use, redirect-only value
    (vendor-confirmed — see leadgen/README.md ADR §7). Stored so the funnel
    can use it, expired so nobody hands out a dead link, and kept out of the
    audit trail regardless."""

    def _inject(self, buyer, lead, response):
        connector = HypernetConnector(buyer)
        mock_resp = MagicMock(ok=True, content=b'{}', json=lambda: response)
        with patch('leadgen.connectors.requests.request', return_value=mock_resp):
            connector.inject_lead(lead)
        lead.refresh_from_db()
        return connector

    def test_redirect_is_captured_on_injection(self, hypernet_buyer, lead):
        url = 'https://desperados.hn-crm.com/autologin?token=ONE-SHOT'
        self._inject(hypernet_buyer, lead, {'success': True, 'leadId': 'x', 'redirectUrl': url})
        assert lead.get_broker_redirect_url() == url
        assert lead.broker_redirect_captured_at is not None

    def test_redirect_is_stored_encrypted_not_in_plaintext(self, hypernet_buyer, lead):
        url = 'https://desperados.hn-crm.com/autologin?token=ONE-SHOT'
        self._inject(hypernet_buyer, lead, {'success': True, 'leadId': 'x', 'redirectUrl': url})
        assert lead.broker_redirect_url_encrypted
        assert 'ONE-SHOT' not in lead.broker_redirect_url_encrypted

    def test_redirect_expires_after_three_minutes(self, hypernet_buyer, lead):
        """The whole point of storing captured_at. A reader past the window
        gets None, never a stale link."""
        from django.utils import timezone

        url = 'https://desperados.hn-crm.com/autologin?token=ONE-SHOT'
        self._inject(hypernet_buyer, lead, {'success': True, 'leadId': 'x', 'redirectUrl': url})
        assert lead.get_broker_redirect_url() == url

        lead.broker_redirect_captured_at = timezone.now() - timedelta(minutes=3, seconds=1)
        assert lead.broker_redirect_is_expired is True
        assert lead.get_broker_redirect_url() is None

    def test_redirect_still_valid_just_inside_the_window(self, hypernet_buyer, lead):
        from django.utils import timezone

        url = 'https://desperados.hn-crm.com/autologin?token=ONE-SHOT'
        self._inject(hypernet_buyer, lead, {'success': True, 'leadId': 'x', 'redirectUrl': url})
        lead.broker_redirect_captured_at = timezone.now() - timedelta(minutes=2, seconds=55)
        assert lead.broker_redirect_is_expired is False
        assert lead.get_broker_redirect_url() == url

    def test_a_lead_with_no_redirect_reports_expired_not_an_error(self, hypernet_buyer, lead):
        assert lead.broker_redirect_is_expired is True
        assert lead.get_broker_redirect_url() is None

    def test_response_without_a_redirect_stores_nothing(self, hypernet_buyer, lead):
        self._inject(hypernet_buyer, lead, {'success': True, 'leadId': 'x'})
        assert lead.broker_redirect_url_encrypted == ''
        assert lead.broker_redirect_captured_at is None

    def test_capture_advances_updated_at(self, hypernet_buyer, lead):
        """Storing the redirect is a lead mutation and must go through
        LeadQuerySet.touch(), or the change is invisible to the
        ?updated_since= reconcile poll."""
        before = lead.updated_at
        self._inject(hypernet_buyer, lead,
                     {'success': True, 'leadId': 'x', 'redirectUrl': 'https://x/'})
        assert lead.updated_at > before

    def test_unsaved_lead_stores_nothing_and_does_not_raise(self, hypernet_buyer):
        """admin_views.buyer_test_connection injects an UNSAVED probe lead —
        there is nothing to attach a redirect to and no consumer to send."""
        probe = Lead(first_name='Nexora', last_name='TestConnection',
                     email='nexora-test-connection@example.invalid', phone='+10000000000')
        connector = HypernetConnector(hypernet_buyer)
        mock_resp = MagicMock(ok=True, content=b'{}',
                              json=lambda: {'success': True, 'redirectUrl': 'https://x/'})
        with patch('leadgen.connectors.requests.request', return_value=mock_resp):
            connector.inject_lead(probe)
        assert probe.pk is None

    def test_a_storage_failure_never_fails_a_delivered_lead(self, hypernet_buyer, lead):
        """Best-effort by design: a lead the buyer ACCEPTED must not be
        recorded as failed because a 3-minute convenience could not be
        persisted.

        The password is pre-stored so get_or_create_password takes its
        read-back path and never calls encrypt_secret — otherwise this patch
        would break the password path first and prove nothing about the
        redirect. That path is deliberately NOT best-effort: failing to
        provision a credential must stop the delivery, not proceed silently.
        """
        from nexora.crypto import encrypt_secret

        Lead.objects.filter(pk=lead.pk).update(
            broker_password_encrypted=encrypt_secret('already-provisioned'))
        lead.refresh_from_db()

        connector = HypernetConnector(hypernet_buyer)
        mock_resp = MagicMock(ok=True, content=b'{}', json=lambda: {
            'success': True, 'leadId': 'abc', 'redirectUrl': 'https://x/'})
        with patch('leadgen.connectors.requests.request', return_value=mock_resp):
            with patch('leadgen.connectors.encrypt_secret', side_effect=RuntimeError('boom')):
                response = connector.inject_lead(lead)

        assert connector.parse_injection_result(response) == ('abc', 'delivered', '')
        lead.refresh_from_db()
        assert lead.broker_redirect_url_encrypted == ''

    def test_redirect_never_reaches_the_audit_copy_even_once_stored(self, hypernet_buyer, lead):
        """Storing it for the funnel must not weaken the audit exclusion —
        these are two independent decisions and both must hold."""
        url = 'https://desperados.hn-crm.com/autologin?token=ONE-SHOT'
        connector = self._inject(hypernet_buyer, lead,
                                 {'success': True, 'leadId': 'x', 'redirectUrl': url})
        audited = connector.sanitize_response_for_audit(
            {'success': True, 'leadId': 'x', 'redirectUrl': url})
        assert audited['redirectUrl'] == '[redacted]'
        assert 'ONE-SHOT' not in str(audited)
        # ...and it IS retrievable through the sanctioned path.
        assert lead.get_broker_redirect_url() == url


@pytest.mark.django_db
class TestStatusSyncIsExplicitlyUnimplemented:
    """Hypernet's GET filters by date window, not by an ID list, so the base
    class's Ids= call would be accepted and return an unrelated page. Loudly
    unimplemented beats silently wrong."""

    def test_fetch_lead_statuses_raises(self, hypernet_buyer):
        with pytest.raises(NotImplementedError):
            HypernetConnector(hypernet_buyer).fetch_lead_statuses(['abc'])

    def test_parse_status_sync_results_raises(self, hypernet_buyer):
        with pytest.raises(NotImplementedError):
            HypernetConnector(hypernet_buyer).parse_status_sync_results({'count': 0, 'rows': []})


@pytest.mark.django_db
class TestTransport:
    """Two things the connector inherits but that are worth pinning for THIS
    box, since both are configured on the BoxType rather than in code."""

    def test_posts_the_nested_body_to_the_documented_path_with_the_api_key_header(
            self, hypernet_buyer, lead):
        connector = HypernetConnector(hypernet_buyer)
        mock_resp = MagicMock(
            ok=True, content=b'{}',
            json=lambda: {'success': True, 'leadId': 'abc', 'redirectUrl': 'https://x/'})

        with patch('leadgen.connectors.requests.request', return_value=mock_resp) as mock_req:
            connector.inject_lead(lead)

        args, kwargs = mock_req.call_args
        assert args[0] == 'POST'
        assert args[1] == 'https://desperados.hn-crm.com/api/external/integration/lead'
        assert kwargs['headers']['x-api-key'] == 'fake-test-key-not-the-real-one'
        assert kwargs['json']['profile']['email'] == 'john.doe@example.com'
        assert kwargs['json']['affc'] == AFFC

    def test_api_key_never_appears_in_the_audited_request_payload(self, hypernet_buyer, lead):
        """The audit trail (LeadInjection.request_payload) is built from
        build_payload() — the key travels in a header and must never reach
        it. Same guarantee the base connector's docstring makes."""
        payload = HypernetConnector(hypernet_buyer).build_payload(lead)
        assert 'fake-test-key-not-the-real-one' not in str(payload)

    def test_batch_injection_is_refused(self, hypernet_buyer, lead):
        with pytest.raises(LeadBuyerError):
            HypernetConnector(hypernet_buyer).inject_batch([lead])
