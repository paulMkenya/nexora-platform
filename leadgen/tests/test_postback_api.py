"""Self-service postback registration over the API.

WHY: the person who wires up a postback is a developer at the traffic source,
and they are usually not the person holding the portal password. The
integration therefore stalled on a human handoff — and until it completed,
every status change was invisible to the affiliate unless they polled.

"WITHOUT LOGGING IN" MEANS WITHOUT A PORTAL SESSION, NOT UNAUTHENTICATED. These
endpoints take the same API key as lead submission. An anonymous registration
endpoint would let anyone point a postback carrying another affiliate's lead
data — email, phone, status — at a server they control. The auth and ownership
tests below are the ones that must never be relaxed.
"""
import pytest

from leadgen.models import AffiliatePostbackConfig

LIST_URL = '/api/postbacks'


def _auth(key):
    return {'HTTP_AUTHORIZATION': f'ApiKey {key.secret}'}


@pytest.fixture
def other_affiliate(db, brand):
    from django.contrib.auth import get_user_model
    from public_api.models import APIKey
    from user_profile.models import Profile

    User = get_user_model()
    u = User.objects.create_user(username='pb_other', password='x', email='o@pb.test')
    u.profile.role = Profile.Role.AFFILIATE
    u.profile.brand = brand
    u.profile.save(update_fields=['role', 'brand'])
    return u, APIKey.generate(user=u, name='other', requests_per_hour=1000)


# --- auth is mandatory --------------------------------------------------------

@pytest.mark.django_db
def test_anonymous_cannot_list_or_register(client):
    assert client.get(LIST_URL).status_code == 401
    assert client.post(LIST_URL, data={'url': 'https://x.test/pb'},
                       content_type='application/json').status_code == 401


@pytest.mark.django_db
def test_a_non_affiliate_key_is_refused(client, advertiser_api_key):
    resp = client.post(LIST_URL, data={'url': 'https://example.com/pb'},
                       content_type='application/json', **_auth(advertiser_api_key))
    assert resp.status_code == 403


# --- registering --------------------------------------------------------------

@pytest.mark.django_db
def test_register_returns_the_secret_exactly_once(client, affiliate_api_key, affiliate_user):
    resp = client.post(LIST_URL, data={'url': 'https://example.com/pb?lead={lead_id}'},
                       content_type='application/json', **_auth(affiliate_api_key))
    assert resp.status_code == 201
    body = resp.json()
    config = AffiliatePostbackConfig.objects.get(pk=body['id'])
    assert config.affiliate == affiliate_user, 'must be owned by the KEY holder'
    assert body['secret'] == config.secret, 'create is the one moment it is readable'

    # ...and never again, on any subsequent read.
    listed = client.get(LIST_URL, **_auth(affiliate_api_key)).json()['results'][0]
    detail = client.get(f'{LIST_URL}/{config.pk}', **_auth(affiliate_api_key)).json()
    for representation in (listed, detail):
        assert 'secret' not in representation
        assert config.secret not in str(representation)
        assert representation['secret_set'] is True


@pytest.mark.django_db
def test_affiliate_cannot_register_on_behalf_of_someone_else(
        client, affiliate_api_key, affiliate_user, other_affiliate):
    """A client-supplied `affiliate` must be ignored, not honoured."""
    victim, _ = other_affiliate
    resp = client.post(LIST_URL,
                       data={'url': 'https://example.com/pb', 'affiliate': victim.pk},
                       content_type='application/json', **_auth(affiliate_api_key))
    assert resp.status_code == 201
    assert AffiliatePostbackConfig.objects.get(pk=resp.json()['id']).affiliate == affiliate_user


# --- SSRF -------------------------------------------------------------------

@pytest.mark.django_db
@pytest.mark.parametrize('url', [
    'http://127.0.0.1/pb',
    'http://localhost/pb',
    'http://169.254.169.254/latest/meta-data/',   # cloud metadata
    'ftp://example.com/pb',
    'notaurl',
])
def test_unsafe_urls_are_refused(client, affiliate_api_key, url):
    """leadgen/security.py's fourth call site. An approved affiliate is still an
    external party; without this they could aim our own worker at an internal
    service and read the outcome out of the delivery log."""
    resp = client.post(LIST_URL, data={'url': url},
                       content_type='application/json', **_auth(affiliate_api_key))
    assert resp.status_code == 400
    assert 'url' in resp.json()
    assert not AffiliatePostbackConfig.objects.exists()


# --- ownership on every other verb -------------------------------------------

@pytest.mark.django_db
def test_one_affiliate_cannot_see_or_touch_anothers(client, affiliate_api_key, other_affiliate):
    victim, victim_key = other_affiliate
    theirs = AffiliatePostbackConfig.objects.create(
        affiliate=victim, url='https://victim.example/pb')

    assert client.get(LIST_URL, **_auth(affiliate_api_key)).json()['results'] == []
    assert client.get(f'{LIST_URL}/{theirs.pk}', **_auth(affiliate_api_key)).status_code == 404
    assert client.patch(f'{LIST_URL}/{theirs.pk}', data={'url': 'https://attacker.example/pb'},
                        content_type='application/json',
                        **_auth(affiliate_api_key)).status_code == 404
    assert client.delete(f'{LIST_URL}/{theirs.pk}', **_auth(affiliate_api_key)).status_code == 404

    theirs.refresh_from_db()
    assert theirs.url == 'https://victim.example/pb'
    assert theirs.is_active is True


# --- update / delete ----------------------------------------------------------

@pytest.mark.django_db
def test_update_and_status_filter(client, affiliate_api_key, affiliate_user):
    config = AffiliatePostbackConfig.objects.create(
        affiliate=affiliate_user, url='https://example.com/old')
    resp = client.patch(f'{LIST_URL}/{config.pk}',
                        data={'url': 'https://example.com/new',
                              'subscribed_statuses': ['ftd', 'no_answer']},
                        content_type='application/json', **_auth(affiliate_api_key))
    assert resp.status_code == 200
    config.refresh_from_db()
    assert config.url == 'https://example.com/new'
    assert config.subscribed_statuses == ['ftd', 'no_answer']


@pytest.mark.django_db
def test_an_unknown_status_is_rejected_not_silently_stored(client, affiliate_api_key):
    """A typo here would mean a postback that simply never fires — the least
    debuggable outcome for an integrator."""
    resp = client.post(LIST_URL,
                       data={'url': 'https://example.com/pb', 'subscribed_statuses': ['FTD!!']},
                       content_type='application/json', **_auth(affiliate_api_key))
    assert resp.status_code == 400
    assert 'subscribed_statuses' in resp.json()


@pytest.mark.django_db
def test_delete_deactivates_and_keeps_the_delivery_history(
        client, affiliate_api_key, affiliate_user, brand, offer):
    """PostbackDelivery rows are the audit trail of what we sent and what came
    back — the evidence a billing dispute turns on. A hard delete would cascade
    that away."""
    from leadgen.models import Lead, LeadStatusEvent, PostbackDelivery

    config = AffiliatePostbackConfig.objects.create(
        affiliate=affiliate_user, url='https://example.com/pb')
    # A delivery is always ABOUT a status event (FK, non-null) — that pairing is
    # what makes the log an audit trail rather than a list of HTTP calls.
    lead = Lead.objects.create(
        brand=brand, affiliate=affiliate_user, offer=offer,
        intake_channel=Lead.CHANNEL_AFFILIATE_API,
        email='pb@example.test', phone='+15551230000')
    event = LeadStatusEvent.objects.create(
        lead=lead, from_status='', to_status='ftd',
        source=LeadStatusEvent.SOURCE_OPERATOR, lead_seq=1)
    PostbackDelivery.objects.create(config=config, status_event=event, url=config.url,
                                    status='delivered', response_status_code=200)

    assert client.delete(f'{LIST_URL}/{config.pk}', **_auth(affiliate_api_key)).status_code == 204
    config.refresh_from_db()
    assert config.is_active is False
    assert PostbackDelivery.objects.filter(config=config).count() == 1
