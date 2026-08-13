"""Tests for lead attribution — the marketing detail a lead carries from an
affiliate's system through to a buyer box. See docs/lead-attribution.md.

Three things here are worth more than the rest, because each one failing is
SILENT rather than loud:

1. **A buyer whose field_mapping names none of the new sources must send
   byte-for-byte what it sent before this feature existed.** op-brandy and
   Hypernet are live. `MAPPABLE_LEAD_FIELDS` entries are sent to every buyer
   whether mapped or not, so had `language`/`attribution` been added there,
   both boxes would have started receiving new keys, uninvited, on deploy.
   TestNoRegressionForUnmappedBuyers pins the opt-in rule that prevents it.

2. **An unknown submitted field is reported back.** Before `ignored_fields`,
   an affiliate could POST `MPC_3`, get a 201, and never learn the value went
   nowhere.

3. **Empty attribution values are dropped, not stored as ''.** For several
   boxes an empty string is a real value that overwrites a default, while an
   absent key leaves the default alone.
"""
from unittest.mock import patch

import pytest
from rest_framework.test import APIClient

from leadgen.connectors import LeadBuyerConnector, TrackBoxConnector
from leadgen.models import BoxType, Lead, LeadBuyer

SUBMIT_URL = '/api/leads/submit'
BATCH_URL = '/api/leads/submit/batch'

BASE_SUBMISSION = {
    'email': 'jane@example.com',
    'phone': '+15551234567',
}


def _client_with_key(key):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f'ApiKey {key.secret}')
    return client


@pytest.fixture
def eligible_offer(db, brand):
    """An Offer that passes offers_for_affiliate' gating — the shared `offer`
    fixture's advertiser starts PENDING/unverified, which does not. Mirrors
    test_api_views.py's fixture of the same name; see its docstring for why
    it is built standalone rather than on the shared fixtures."""
    from django.contrib.auth import get_user_model

    from offer.models import Advertiser, Offer

    user = get_user_model().objects.create_user(username='attr_offer_advertiser', password='pass')
    advertiser = Advertiser.objects.create(
        user=user, company='AttrCo', email='attr-advertiser@test.com',
        advertiser_status=Advertiser.AdvertiserStatus.APPROVED, email_verified=True,
    )
    return Offer.objects.create(
        title='Attribution Test Offer', tracking_link='https://t.leadgen.test/attr-click',
        brand=brand, advertiser=advertiser,
    )


@pytest.fixture
def submit(affiliate_api_key, eligible_offer):
    """POST one submission, with offer_id and the required contact fields
    filled in, and return the response. Delivery is patched out — every test
    here is about what INTAKE recorded, not about reaching a buyer."""
    client = _client_with_key(affiliate_api_key)

    def _submit(**overrides):
        body = dict(BASE_SUBMISSION, offer_id=eligible_offer.pk, **overrides)
        with patch('leadgen.api_views.maybe_auto_inject'):
            return client.post(SUBMIT_URL, body, format='json')

    return _submit


# --- intake ------------------------------------------------------------------

@pytest.mark.django_db
class TestIntakeStoresAttribution:
    def test_named_fields_land_in_attribution(self, submit):
        resp = submit(funnel='crypto-quiz-v2', campaign='summer-crypto',
                      medium='paid-social', term='bitcoin-broker', ad='video-ad-3')
        assert resp.status_code == 201

        lead = Lead.objects.get(pk=resp.data['id'])
        assert lead.attribution == {
            'funnel': 'crypto-quiz-v2', 'campaign': 'summer-crypto',
            'medium': 'paid-social', 'term': 'bitcoin-broker', 'ad': 'video-ad-3',
        }

    def test_language_is_a_column_and_is_upper_cased(self, submit):
        # 'en', 'EN' and 'En' must be ONE value in reporting and one value on
        # the wire — boxes in this vertical document the upper form.
        resp = submit(language='en')
        assert resp.status_code == 201
        assert Lead.objects.get(pk=resp.data['id']).language == 'EN'

    def test_sub_slots_land_in_attribution(self, submit):
        resp = submit(sub1='a', sub3='c')
        lead = Lead.objects.get(pk=resp.data['id'])
        assert lead.attribution == {'sub1': 'a', 'sub3': 'c'}

    def test_extra_keys_are_merged_in(self, submit):
        resp = submit(campaign='summer', extra={'risk_band': 'A', 'MPC_7': 'x'})
        lead = Lead.objects.get(pk=resp.data['id'])
        assert lead.attribution == {'campaign': 'summer', 'risk_band': 'A', 'MPC_7': 'x'}

    def test_empty_values_are_dropped_not_stored_blank(self, submit):
        # A stored '' would be FORWARDED as a real blank value, which several
        # boxes treat differently from an absent key.
        resp = submit(campaign='summer', medium='', sub1='   ', extra={'k': ''})
        lead = Lead.objects.get(pk=resp.data['id'])
        assert lead.attribution == {'campaign': 'summer'}

    def test_a_lead_with_no_attribution_stores_an_empty_dict(self, submit):
        resp = submit()
        lead = Lead.objects.get(pk=resp.data['id'])
        assert lead.attribution == {}
        assert lead.language == ''


@pytest.mark.django_db
class TestIntakeValidation:
    def test_extra_may_not_shadow_a_named_field(self, submit):
        # Allowing it would make two requests that look equivalent behave
        # differently depending on write order inside build_attribution.
        resp = submit(extra={'campaign': 'sneaky'})
        assert resp.status_code == 400
        assert 'campaign' in str(resp.data['extra'])

    def test_extra_key_count_is_bounded(self, submit):
        resp = submit(extra={f'k{i}': 'v' for i in range(21)})
        assert resp.status_code == 400

    def test_extra_key_charset_is_bounded(self, submit):
        resp = submit(extra={'not a key!': 'v'})
        assert resp.status_code == 400

    def test_a_nonsense_language_is_rejected(self, submit):
        assert submit(language='English').status_code == 400

    def test_a_region_qualified_language_is_accepted(self, submit):
        resp = submit(language='en-GB')
        assert resp.status_code == 201
        assert Lead.objects.get(pk=resp.data['id']).language == 'EN-GB'


@pytest.mark.django_db
class TestIgnoredFieldsAreReported:
    def test_an_unknown_field_is_named_in_the_response(self, submit):
        resp = submit(MPC_3='oops', lg='EN')
        assert resp.status_code == 201
        assert resp.data['ignored_fields'] == ['MPC_3', 'lg']

    def test_an_unknown_field_is_still_accepted_not_rejected(self, submit):
        # Advisory, never a 400: rejecting would break any affiliate already
        # sending a field we don't read.
        resp = submit(MPC_3='oops')
        assert resp.status_code == 201
        assert Lead.objects.filter(pk=resp.data['id']).exists()

    def test_a_clean_submission_carries_no_ignored_fields_key(self, submit):
        # Absent, not empty — the common case is unchanged for existing
        # integrations.
        assert 'ignored_fields' not in submit(campaign='summer').data

    def test_batch_reports_per_item(self, affiliate_api_key, eligible_offer):
        client = _client_with_key(affiliate_api_key)
        resp = client.post(BATCH_URL, {'leads': [
            dict(BASE_SUBMISSION, offer_id=eligible_offer.pk, source_id='one', bogus='x'),
            dict(BASE_SUBMISSION, offer_id=eligible_offer.pk, source_id='two'),
        ]}, format='json')

        assert resp.status_code == 201
        added = resp.data['addedLeads']
        assert added[0]['ignored_fields'] == ['bogus']
        assert 'ignored_fields' not in added[1]


@pytest.mark.django_db
class TestPullEchoesAttribution:
    def test_attribution_and_language_come_back(self, submit, affiliate_api_key):
        submit(campaign='summer', sub1='a', language='DE')
        client = _client_with_key(affiliate_api_key)

        row = client.get('/api/leads').data['results'][0]
        assert row['language'] == 'DE'
        assert row['attribution'] == {'campaign': 'summer', 'sub1': 'a'}
        assert row['sub1'] == 'a'

    def test_a_legacy_lead_still_echoes_subs_from_raw_payload(self, affiliate_user, affiliate_api_key):
        # sub1..sub5 lived in raw_payload before Lead.attribution existed.
        # Affiliates reconcile against this endpoint, so their historical
        # leads must keep echoing the values they always did.
        Lead.objects.create(
            intake_channel=Lead.CHANNEL_AFFILIATE_API, affiliate=affiliate_user,
            email='old@example.com', phone='+15550000000',
            raw_payload={'sub1': 'legacy-value'},
        )
        client = _client_with_key(affiliate_api_key)

        row = client.get('/api/leads').data['results'][0]
        assert row['sub1'] == 'legacy-value'


# --- forwarding ---------------------------------------------------------------

@pytest.fixture
def plain_box_type(db):
    """A buyer box configured exactly as the live ones are: its mapping names
    only the MAPPABLE_LEAD_FIELDS core, and nothing else."""
    return BoxType.objects.create(
        name='Plain', slug='plain-test',
        connector_class='leadgen.connectors.LeadBuyerConnector',
        default_field_mapping={'firstname': 'firstName', 'email': 'email', 'phone': 'phone'},
    )


@pytest.fixture
def plain_buyer(db, brand, plain_box_type):
    return LeadBuyer.objects.create(
        brand=brand, box_type=plain_box_type, name='Plain Buyer', slug='plain-buyer-test',
        base_url='https://plain.example.com',
    )


@pytest.fixture
def rich_lead(db):
    return Lead.objects.create(
        intake_channel=Lead.CHANNEL_AFFILIATE_API,
        first_name='Jane', last_name='Doe',
        email='jane@example.com', phone='+15551234567',
        source_id='click-abc', language='DE',
        attribution={'funnel': 'quiz-v2', 'campaign': 'summer', 'sub1': 'a', 'risk_band': 'A'},
    )


@pytest.mark.django_db
class TestNoRegressionForUnmappedBuyers:
    """THE regression guard. op-brandy and Hypernet are live and their
    mappings name none of the new sources; their payloads must not change."""

    def test_an_unmapped_buyer_gets_no_new_keys(self, plain_buyer, rich_lead):
        payload = LeadBuyerConnector(plain_buyer).build_payload(rich_lead)

        # Exactly the MAPPABLE_LEAD_FIELDS core and nothing else: the three
        # this box renames, plus the two it doesn't (which keep our own
        # names, per _map_field). `vertical` is blank on this lead, so it is
        # skipped as it always was.
        assert payload == {
            'firstName': 'Jane',
            'lastname': 'Doe',
            'email': 'jane@example.com',
            'phone': '+15551234567',
            'source_id': 'click-abc',
        }

    def test_no_attribution_key_leaks_into_an_unmapped_payload(self, plain_buyer, rich_lead):
        payload = LeadBuyerConnector(plain_buyer).build_payload(rich_lead)
        assert 'language' not in payload
        assert 'attribution' not in payload
        assert not any(k in payload for k in ('funnel', 'campaign', 'sub1', 'risk_band'))

    def test_build_extra_payload_is_empty_for_an_unmapped_buyer(self, plain_buyer, rich_lead):
        assert LeadBuyerConnector(plain_buyer).build_extra_payload(rich_lead) == {}


@pytest.mark.django_db
class TestOptInForwarding:
    def test_a_mapped_source_is_emitted_under_the_buyers_name(self, plain_buyer, rich_lead):
        plain_buyer.field_mapping = {'language': 'lg', 'attribution.funnel': 'so'}

        extra = LeadBuyerConnector(plain_buyer).build_extra_payload(rich_lead)
        assert extra == {'lg': 'DE', 'so': 'quiz-v2'}

    def test_an_extra_key_can_be_mapped_too(self, plain_buyer, rich_lead):
        # The escape hatch that lets a brand fill MPC_6..MPC_12 without a
        # migration.
        plain_buyer.field_mapping = {'attribution.risk_band': 'MPC_6'}
        assert LeadBuyerConnector(plain_buyer).build_extra_payload(rich_lead) == {'MPC_6': 'A'}

    def test_a_mapped_but_absent_source_is_omitted_not_sent_blank(self, plain_buyer, rich_lead):
        plain_buyer.field_mapping = {'attribution.medium': 'medium'}
        assert LeadBuyerConnector(plain_buyer).build_extra_payload(rich_lead) == {}

    def test_a_buyer_override_beats_the_box_type_default(self, plain_buyer, rich_lead):
        plain_buyer.box_type.default_field_mapping['attribution.funnel'] = 'so'
        plain_buyer.box_type.save(update_fields=['default_field_mapping'])
        plain_buyer.field_mapping = {'attribution.funnel': 'funnel_name'}

        extra = LeadBuyerConnector(plain_buyer).build_extra_payload(rich_lead)
        assert extra == {'funnel_name': 'quiz-v2'}


@pytest.mark.django_db
class TestTrackBoxCarriesAttribution:
    """The box this was built for. Its real mapping is seeded by
    manage.py seed_trackbox_box; the literals here mirror it."""

    @pytest.fixture
    def buyer(self, brand):
        box_type = BoxType.objects.create(
            name='TrackBox', slug='trackbox-attr-test',
            connector_class='leadgen.connectors.TrackBoxConnector',
            auth_type=BoxType.AUTH_API_KEY_HEADER, auth_param_name='x-api-key',
            single_endpoint_path='/api/signup/procform',
            default_field_mapping={
                'firstname': 'firstname', 'lastname': 'lastname',
                'email': 'email', 'phone': 'phone', 'source_id': 'sub',
                'language': 'lg',
                'attribution.funnel': 'so',
                'attribution.campaign': 'campaign',
                'attribution.sub1': 'MPC_1',
            },
        )
        buyer = LeadBuyer.objects.create(
            brand=brand, box_type=box_type, name='TrackBox attr', slug='trackbox-attr',
            base_url='https://platform.traffixworld.com',
            extra_payload_fields={'ai': '2958839', 'ci': '1', 'gi': '843',
                                  'so': 'exxtraffic', 'lg': 'EN'},
        )
        buyer.set_extra_credentials({'username': 'u', 'password': 'p'})
        buyer.save(update_fields=['extra_credentials_encrypted'])
        return buyer

    def test_the_signup_body_carries_the_leads_own_attribution(self, buyer, rich_lead):
        payload = TrackBoxConnector(buyer).build_payload(rich_lead)

        assert payload['campaign'] == 'summer'
        assert payload['MPC_1'] == 'a'

    def test_a_per_lead_value_overrides_the_static_default(self, buyer, rich_lead):
        # `so` and `lg` are per-buyer STATICS in extra_payload_fields. The
        # whole point of this feature is that a lead that knows its own
        # funnel wins — otherwise every lead reports identically in the
        # buyer's own optimisation screens.
        payload = TrackBoxConnector(buyer).build_payload(rich_lead)

        assert payload['so'] == 'quiz-v2'
        assert payload['lg'] == 'DE'

    def test_a_lead_without_attribution_still_gets_the_statics(self, buyer):
        bare = Lead.objects.create(
            intake_channel=Lead.CHANNEL_LANDING_PAGE,
            email='bare@example.com', phone='+15551234567',
        )
        payload = TrackBoxConnector(buyer).build_payload(bare)

        assert payload['so'] == 'exxtraffic'
        assert payload['lg'] == 'EN'
        assert 'campaign' not in payload

    def test_the_buyer_constants_are_never_per_lead(self, buyer, rich_lead):
        # ai/ci/gi identify the BUYER RELATIONSHIP. A lead must never be able
        # to influence them.
        payload = TrackBoxConnector(buyer).build_payload(rich_lead)
        assert (payload['ai'], payload['ci'], payload['gi']) == ('2958839', '1', '843')


# --- the landing-page channel --------------------------------------------------

@pytest.mark.django_db
class TestLandingPageCapturesUtm:
    def test_utm_params_are_mapped_onto_the_canonical_names(self, client, offer):
        with patch('leadgen.public_views.maybe_auto_inject'):
            resp = client.post(
                f'/l/{offer.pk}/?utm_source=fb-quiz&utm_campaign=summer'
                f'&utm_medium=paid-social&utm_term=broker&utm_content=ad-3',
                {'email': 'walkin@example.com', 'phone': '+15551234567', 'lang': 'es'},
            )
        assert resp.status_code == 200

        lead = Lead.objects.get(email='walkin@example.com')
        assert lead.attribution == {
            'funnel': 'fb-quiz', 'campaign': 'summer',
            'medium': 'paid-social', 'term': 'broker', 'ad': 'ad-3',
        }
        assert lead.language == 'ES'

    def test_posted_values_beat_the_query_string(self, client, offer):
        # The hidden inputs are the reliable carrier; a stale query string on
        # the submit URL must not win over what the form actually sent.
        with patch('leadgen.public_views.maybe_auto_inject'):
            client.post(
                f'/l/{offer.pk}/?utm_source=from-query',
                {'email': 'posted@example.com', 'phone': '+15551234567',
                 'utm_source': 'from-form'},
            )
        assert Lead.objects.get(email='posted@example.com').attribution['funnel'] == 'from-form'

    def test_hidden_inputs_round_trip_the_landing_query_string(self, client, offer):
        # The ad click lands on the GET; the values have to survive to the
        # POST without depending on the form action keeping the query string.
        html = client.get(f'/l/{offer.pk}/?utm_source=fb-quiz').content.decode()

        assert 'name="utm_source"' in html
        assert 'value="fb-quiz"' in html
