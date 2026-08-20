"""The three fixes for the Nexora-contract vs buyer-contract gap (2026-08-20).

Our inbound API and a buyer box's API are different contracts, and only the
first is visible to the affiliate. Everything here pins a place where that gap
used to lose leads or corrupt a buyer's reporting SILENTLY — no exception, no
failed row, nothing to notice:

  1. Hypernet requires `geo`; our `country` is optional. A lead submitted
     without it got 201 from us and `("geo" is required)` from the box.
  2. The Hypernet BoxType maps `vertical -> funnel`, and mapped lead values
     beat static constants — so an affiliate-supplied `vertical` rewrote the
     box's agreed reporting label, and Hypernet's `funnel` is free text so it
     never complained.
  3. `Lead.language` was never mapped to their `lang`, so a correctly-supplied
     language was dropped while the doc promised buyers received it.

Failure mode being tested is silence, so each test asserts the OBSERVABLE
artifact — the payload that goes on the wire, the HTTP status, whether a row
exists — rather than that some function was called.
"""
import pytest

from leadgen.connectors import HypernetConnector, get_connector
from leadgen.models import BoxType, Lead, LeadBuyer, RoutingRule
from leadgen.requirements import missing_buyer_requirements

HYPERNET_MAPPING = {
    'firstname': 'profile.firstName',
    'lastname': 'profile.lastName',
    'email': 'profile.email',
    'phone': 'profile.phone',
    'vertical': 'funnel',
    'source_id': 'subId',
    'language': 'lang',
}

STATICS = {
    'affc': 'AFF-TEST', 'bxc': 'BX-TEST', 'vtc': 'VT-TEST',
    'lang': 'en', 'landingLang': 'en', 'landingURL': 'https://lander.test/1/',
    'funnel': 'agreed-funnel-label',
}


@pytest.fixture
def hypernet_buyer(db, brand):
    box = BoxType.objects.create(
        name='Hypernet', slug='hypernet-req-test',
        connector_class='leadgen.connectors.HypernetConnector',
        auth_type=BoxType.AUTH_API_KEY_HEADER, auth_param_name='x-api-key',
        single_endpoint_path='/api/external/integration/lead',
        batch_endpoint_path='', fetch_endpoint_path='/api/external/integration/lead',
        batch_max_size=1, default_field_mapping=HYPERNET_MAPPING,
    )
    b = LeadBuyer.objects.create(
        brand=brand, box_type=box, name='Hypernet Test', slug='hypernet-req-buyer',
        is_active=True, auto_inject=False, base_url='https://box.test',
        extra_payload_fields=dict(STATICS),
    )
    b.set_api_key('fake-key-not-a-real-secret')
    b.save(update_fields=['api_key_encrypted'])
    return b


@pytest.fixture
def route_to_hypernet(db, brand, hypernet_buyer):
    return RoutingRule.objects.create(
        brand=brand, buyer=hypernet_buyer, name='all -> hypernet',
        priority=100, is_active=True,
    )


def _lead(brand, offer, affiliate, **kw):
    base = dict(
        brand=brand, offer=offer, affiliate=affiliate,
        intake_channel=Lead.CHANNEL_AFFILIATE_API,
        first_name='A', last_name='B', email='a@b.test', phone='+447700900123',
        country_iso2='GB', vertical='', language='', source_id='s1',
    )
    base.update(kw)
    return Lead(**base)


# --- 1. the requirement gate -------------------------------------------------

def test_hypernet_declares_country_required():
    """The requirement is a property of the CONNECTOR, not of intake."""
    assert 'country_iso2' in HypernetConnector.REQUIRED_LEAD_FIELDS


def test_missing_country_is_reported_under_its_api_name(
        brand, offer, affiliate_user, route_to_hypernet):
    lead = _lead(brand, offer, affiliate_user, country_iso2='')
    # 'country', not 'country_iso2' — the affiliate never sees our column name.
    assert missing_buyer_requirements(lead) == ['country']


def test_country_present_is_accepted(brand, offer, affiliate_user, route_to_hypernet):
    assert missing_buyer_requirements(_lead(brand, offer, affiliate_user)) == []


def test_unroutable_lead_is_not_the_affiliates_fault(brand, offer, affiliate_user):
    """No routing rule => no destination => nothing to demand. An unrouted lead
    is an operator's gap to fix (redrive_leads recovers it); rejecting the
    affiliate for it would blame the wrong party and throw traffic away."""
    assert missing_buyer_requirements(_lead(brand, offer, affiliate_user, country_iso2='')) == []


def test_buyer_without_declared_requirements_demands_nothing(
        brand, offer, affiliate_user, buyer):
    """The generic connector opts out, so every un-probed box keeps today's
    exact intake behaviour."""
    RoutingRule.objects.create(brand=brand, buyer=buyer, priority=100, is_active=True)
    assert missing_buyer_requirements(_lead(brand, offer, affiliate_user, country_iso2='')) == []


# --- 2. pinning --------------------------------------------------------------

def test_mapped_vertical_hijacks_funnel_when_not_pinned(
        brand, offer, affiliate_user, hypernet_buyer):
    """The bug, pinned as a regression test: default precedence lets an
    affiliate-supplied value overwrite the box's agreed label."""
    payload = get_connector(hypernet_buyer).build_payload(
        _lead(brand, offer, affiliate_user, vertical='whatever-they-sent'))
    assert payload['funnel'] == 'whatever-they-sent'


def test_pinning_funnel_keeps_the_agreed_label(
        brand, offer, affiliate_user, hypernet_buyer):
    hypernet_buyer.pinned_payload_fields = ['funnel']
    hypernet_buyer.save(update_fields=['pinned_payload_fields'])
    payload = get_connector(hypernet_buyer).build_payload(
        _lead(brand, offer, affiliate_user, vertical='whatever-they-sent'))
    assert payload['funnel'] == 'agreed-funnel-label'


def test_pinning_a_key_with_no_static_is_ignored_not_obeyed(
        brand, offer, affiliate_user, hypernet_buyer):
    """Obeying it would DELETE the field instead of fixing it — and `funnel`
    is required, so that would be a 400 on every single lead."""
    hypernet_buyer.extra_payload_fields = {
        k: v for k, v in STATICS.items() if k != 'funnel'}
    hypernet_buyer.pinned_payload_fields = ['funnel']
    hypernet_buyer.save(update_fields=['extra_payload_fields', 'pinned_payload_fields'])
    payload = get_connector(hypernet_buyer).build_payload(
        _lead(brand, offer, affiliate_user, vertical='sent-value'))
    assert payload['funnel'] == 'sent-value'


def test_pinning_leaves_every_other_field_alone(
        brand, offer, affiliate_user, hypernet_buyer):
    hypernet_buyer.pinned_payload_fields = ['funnel']
    hypernet_buyer.save(update_fields=['pinned_payload_fields'])
    payload = get_connector(hypernet_buyer).build_payload(
        _lead(brand, offer, affiliate_user, vertical='x', first_name='Jane'))
    assert payload['profile']['firstName'] == 'Jane'
    assert payload['geo'] == 'GB'


def test_default_is_unpinned_so_live_boxes_are_byte_identical(hypernet_buyer):
    assert hypernet_buyer.pinned_payload_fields == []


# --- 3. language -> lang -----------------------------------------------------

def test_language_reaches_lang_lowercased(brand, offer, affiliate_user, hypernet_buyer):
    """We document language as ISO 639-1 with upper-case examples; they ask
    for lower-case."""
    payload = get_connector(hypernet_buyer).build_payload(
        _lead(brand, offer, affiliate_user, language='PL'))
    assert payload['lang'] == 'pl'


def test_absent_language_leaves_the_box_default_intact(
        brand, offer, affiliate_user, hypernet_buyer):
    """build_extra_payload omits a mapped-but-empty source, so the static
    stands — this is what keeps the change safe for boxes already live."""
    payload = get_connector(hypernet_buyer).build_payload(
        _lead(brand, offer, affiliate_user, language=''))
    assert payload['lang'] == 'en'
    assert payload['landingLang'] == 'en'


@pytest.fixture
def eligible_offer(db, brand):
    """An offer offers_for_affiliate() will actually return.

    The shared `offer` fixture's advertiser is PENDING and unverified, so that
    offer is invisible to every affiliate surface — fine for the routing-key
    probes above, useless for anything that goes through intake or the doc.
    Mirrors test_api_views.py's own eligible_offer for the same reason.
    """
    from django.contrib.auth import get_user_model

    from offer.models import Advertiser, Offer

    User = get_user_model()
    user = User.objects.create_user(username='req_offer_advertiser', password='pass')
    advertiser = Advertiser.objects.create(
        user=user, company='ReqCo', email='req-advertiser@test.com',
        advertiser_status=Advertiser.AdvertiserStatus.APPROVED, email_verified=True,
    )
    return Offer.objects.create(
        title='Requirement Test Offer', tracking_link='https://t.leadgen.test/req',
        brand=brand, advertiser=advertiser,
    )


# --- 4. the intake boundary --------------------------------------------------
#
# The point of the whole change: the affiliate finds out on the call that
# submitted the lead, not never.

def _submit(client, api_key, offer, **overrides):
    body = {
        'offer_id': offer.pk, 'first_name': 'Jane', 'last_name': 'Doe',
        'email': 'jane@example.test', 'phone': '+447700900123',
        'source_id': 'unique-per-test',
    }
    body.update(overrides)
    return client.post(
        '/api/leads/submit', data=body, content_type='application/json',
        # The Host matters here and only here: _create_lead() takes the lead's
        # brand from request.brand (BrandMiddleware, host-derived, defaulting
        # when no domain matches), and routing filters rules on lead.brand_id.
        # Without the brand's own domain the lead lands in the DEFAULT brand,
        # matches no rule, routes nowhere, and the gate correctly demands
        # nothing — which would make these tests pass for the wrong reason.
        HTTP_HOST='leadgen.test',
        HTTP_AUTHORIZATION=f'ApiKey {api_key.secret}')


@pytest.mark.django_db
def test_submit_without_country_is_rejected_and_writes_no_lead(
        client, affiliate_api_key, eligible_offer, route_to_hypernet):
    before = Lead.objects.count()
    resp = _submit(client, affiliate_api_key, eligible_offer)
    assert resp.status_code == 400
    # DRF-shaped and keyed on the field the affiliate actually omitted, so an
    # integrator handles one error shape rather than two.
    assert 'country' in resp.json()
    assert Lead.objects.count() == before, 'a rejected submission must not leave a row behind'


@pytest.mark.django_db
def test_submit_with_country_succeeds(client, affiliate_api_key, eligible_offer, route_to_hypernet):
    resp = _submit(client, affiliate_api_key, eligible_offer, country='GB')
    assert resp.status_code == 201
    assert Lead.objects.get(pk=resp.json()['id']).country_iso2 == 'GB'


@pytest.mark.django_db
def test_the_error_names_the_offer_so_it_is_actionable(
        client, affiliate_api_key, eligible_offer, route_to_hypernet):
    resp = _submit(client, affiliate_api_key, eligible_offer)
    assert str(eligible_offer.pk) in resp.json()['country'][0]


@pytest.mark.django_db
def test_offer_id_failure_keeps_its_documented_body(client, affiliate_api_key, route_to_hypernet):
    """The generated doc quotes this body verbatim; restructuring _submit_one's
    error return must not have changed it."""
    resp = _submit(client, affiliate_api_key, type('O', (), {'pk': 999999})())
    assert resp.status_code == 400
    assert resp.json() == {'detail': 'offer_id does not resolve to an offer you can send to.'}


@pytest.mark.django_db
def test_batch_rejects_only_the_offending_lead(
        client, affiliate_api_key, eligible_offer, route_to_hypernet):
    resp = client.post(
        '/api/leads/submit/batch',
        data={'leads': [
            {'offer_id': eligible_offer.pk, 'first_name': 'A', 'last_name': 'B',
             'email': 'ok@example.test', 'phone': '+447700900001',
             'source_id': 'batch-ok', 'country': 'GB'},
            {'offer_id': eligible_offer.pk, 'first_name': 'C', 'last_name': 'D',
             'email': 'bad@example.test', 'phone': '+447700900002',
             'source_id': 'batch-bad'},
        ]},
        content_type='application/json',
        HTTP_HOST='leadgen.test',
        HTTP_AUTHORIZATION=f'ApiKey {affiliate_api_key.secret}')
    assert resp.status_code == 201, 'partial success stays 201'
    body = resp.json()
    assert len(body['addedLeads']) == 1
    assert len(body['failedToAddLeads']) == 1
    assert 'country' in body['failedToAddLeads'][0]['errors']


@pytest.mark.django_db
def test_a_dedupe_retry_is_not_turned_into_a_400(
        client, affiliate_api_key, eligible_offer, route_to_hypernet):
    """A dedupe hit returns the ORIGINAL lead and injects nothing, so the
    destination's requirements are not that submission's problem. Checking
    there would turn a harmless retry into a rejection."""
    first = _submit(client, affiliate_api_key, eligible_offer, country='GB', source_id='same-id')
    assert first.status_code == 201
    again = _submit(client, affiliate_api_key, eligible_offer, source_id='same-id')
    assert again.status_code == 200
    assert again.json()['id'] == first.json()['id']


# --- 5. the doc tells them, derived rather than written ----------------------

@pytest.mark.django_db
def test_doc_flags_the_extra_required_field_per_offer(
        rf, affiliate_user, eligible_offer, route_to_hypernet):
    from leadgen.api_doc import build_doc_context

    request = rf.get('/partner/api-docs/', secure=True)
    request.user = affiliate_user
    row = next(o for o in build_doc_context(request, affiliate_user)['offers'] if o['id'] == eligible_offer.pk)
    assert row['required_fields'] == ['country']


@pytest.mark.django_db
def test_doc_claims_nothing_extra_when_the_box_requires_nothing(
        rf, affiliate_user, eligible_offer, brand, buyer):
    from leadgen.api_doc import build_doc_context

    RoutingRule.objects.create(brand=brand, buyer=buyer, priority=100, is_active=True)
    request = rf.get('/partner/api-docs/', secure=True)
    request.user = affiliate_user
    row = next(o for o in build_doc_context(request, affiliate_user)['offers'] if o['id'] == eligible_offer.pk)
    assert row['required_fields'] == []
