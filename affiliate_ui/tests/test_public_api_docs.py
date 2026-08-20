"""The PUBLIC integration doc — no login, safe to forward or embed.

WHY IT EXISTS: an integration document's readers are a traffic source's
developers, who do not have (and should not need) a portal account before they
can read the contract. Handing over a PDF attachment instead goes stale the
moment the API changes — which it did on 2026-08-20, when `country` went from
optional to enforced and every emailed copy started describing behaviour that
no longer existed.

WHAT THESE TESTS ACTUALLY GUARD: the doc is generated from live backend state,
so "publish it" is one edit away from "publish the tenant's data with it". The
disclosure assertions below are the point of this file — they must keep failing
loudly if anyone widens the public context. See
leadgen.api_doc.build_public_doc_context for what is withheld and why.
"""
import pytest
from django.contrib.auth import get_user_model

from brands.models import Brand
from leadgen.models import BoxType, LeadBuyer, RoutingRule
from offer.models import Advertiser, Offer
from public_api.models import APIKey
from user_profile.models import Profile

User = get_user_model()

PUBLIC_URL = '/partner/api-docs/public/'
PUBLIC_PDF = '/partner/api-docs/public/pdf/'
PUBLIC_TEXT = '/partner/api-docs/public/text/'
PRIVATE_URL = '/partner/api-docs/'

HOST = 'pub-brand.test'
SECRET_OFFER_TITLE = 'Confidential Offer Title'


@pytest.fixture
def pub_brand(db):
    return Brand.objects.create(
        slug='pub-brand', name='PubNet', primary_domain=HOST,
        tracking_domain=f't.{HOST}', is_default=True)


@pytest.fixture
def pub_affiliate(db, pub_brand):
    u = User.objects.create_user(username='pub_aff', password='x', email='pub@aff.test')
    u.profile.role = Profile.Role.AFFILIATE
    u.profile.brand = pub_brand
    u.profile.affiliate_status = Profile.AffiliateStatus.APPROVED
    u.profile.email_verified = True
    u.profile.save()
    return u


@pytest.fixture
def pub_offer(db, pub_brand):
    adv_user = User.objects.create_user(username='pub_adv', password='x')
    advertiser = Advertiser.objects.create(
        user=adv_user, brand=pub_brand, company='PubCo', email='adv@pub.test',
        advertiser_status=Advertiser.AdvertiserStatus.APPROVED, email_verified=True)
    return Offer.objects.create(
        title=SECRET_OFFER_TITLE, tracking_link='https://t.pub.test/c',
        brand=pub_brand, advertiser=advertiser)


@pytest.fixture
def hypernet_route(db, pub_brand):
    """A buyer that declares a REQUIRED_LEAD_FIELDS, so the conditional note has
    something real to derive."""
    bt = BoxType.objects.create(
        name='Hypernet', slug='pub-hypernet',
        connector_class='leadgen.connectors.HypernetConnector',
        auth_type=BoxType.AUTH_API_KEY_HEADER, auth_param_name='x-api-key',
        single_endpoint_path='/api/external/integration/lead',
        batch_endpoint_path='', fetch_endpoint_path='/api/external/integration/lead',
        batch_max_size=1)
    b = LeadBuyer.objects.create(
        brand=pub_brand, box_type=bt, name='Pub Buyer', slug='pub-buyer',
        is_active=True, auto_inject=False, base_url='https://pub-buyer.test')
    b.set_api_key('k')
    b.save(update_fields=['api_key_encrypted'])
    RoutingRule.objects.create(brand=pub_brand, buyer=b, priority=100, is_active=True)
    return b


# --- reachable without a login ------------------------------------------------

@pytest.mark.django_db
@pytest.mark.parametrize('url,content_type', [
    (PUBLIC_URL, 'text/html'),
    (PUBLIC_TEXT, 'text/plain'),
])
def test_anonymous_can_read_it(client, pub_brand, url, content_type):
    resp = client.get(url, HTTP_HOST=HOST)
    assert resp.status_code == 200
    assert content_type in resp['Content-Type']


@pytest.mark.django_db
def test_anonymous_can_download_the_pdf(client, pub_brand):
    resp = client.get(PUBLIC_PDF, HTTP_HOST=HOST)
    assert resp.status_code == 200
    # WeasyPrint is present in the test image; if it ever is not, the shared
    # fallback serves HTML rather than 500 — either way this must not redirect.
    assert resp['Content-Type'] in ('application/pdf', 'text/html')


@pytest.mark.django_db
def test_the_private_doc_still_requires_a_login(client, pub_brand):
    """Adding a public variant must not have loosened the personalized one."""
    assert client.get(PRIVATE_URL, HTTP_HOST=HOST).status_code == 302


# --- discloses no tenant data -------------------------------------------------

@pytest.mark.django_db
@pytest.mark.parametrize('url', [PUBLIC_URL, PUBLIC_TEXT])
def test_public_doc_never_leaks_tenant_data(
        client, pub_brand, pub_affiliate, pub_offer, hypernet_route, url):
    key = APIKey.generate(user=pub_affiliate, name='pub key', requests_per_hour=1000)
    from leadgen.models import AffiliatePostbackConfig
    pb = AffiliatePostbackConfig.objects.create(
        affiliate=pub_affiliate, url='https://tz-hub-internal.example/postback')

    body = client.get(url, HTTP_HOST=HOST).content.decode()

    # The TITLE is the disclosure worth asserting. A bare offer id is a small
    # integer that collides with status codes and field lengths all over the
    # page, so asserting on it would be noise, not a check.
    assert SECRET_OFFER_TITLE not in body, 'offer inventory must not be published'
    assert str(key.client_id) not in body, 'API key client_id must not be published'
    assert key.secret not in body, 'a live secret must never appear anywhere'
    assert pb.url not in body, "the affiliate's own postback URL must not be published"
    assert 'pub_aff' not in body, 'no affiliate identity on a public page'


@pytest.mark.django_db
def test_public_doc_does_not_name_another_brands_offer(client, pub_brand, pub_offer):
    """Belt and braces on the multi-tenant rule: the public page is host-scoped,
    and must not surface ANY brand's inventory, including its own."""
    other = Brand.objects.create(slug='other-pub', name='OtherNet',
                                 primary_domain='other-pub.test', is_default=False)
    adv_user = User.objects.create_user(username='other_adv', password='x')
    advertiser = Advertiser.objects.create(
        user=adv_user, brand=other, company='OtherCo', email='adv@other.test',
        advertiser_status=Advertiser.AdvertiserStatus.APPROVED, email_verified=True)
    Offer.objects.create(title='Other Brand Secret Offer', tracking_link='https://x/c',
                         brand=other, advertiser=advertiser)

    body = client.get(PUBLIC_URL, HTTP_HOST=HOST).content.decode()
    assert 'Other Brand Secret Offer' not in body
    assert SECRET_OFFER_TITLE not in body


# --- still a usable contract --------------------------------------------------

@pytest.mark.django_db
def test_public_doc_carries_the_whole_contract(client, pub_brand):
    body = client.get(PUBLIC_TEXT, HTTP_HOST=HOST).content.decode()
    for probe in ('/api/leads/submit', 'Authorization: ApiKey',
                  'offer_id', 'first_name', 'country', 'ftd', '401', '429'):
        assert probe in body, f'public doc is missing {probe!r} — it must be usable on its own'


@pytest.mark.django_db
def test_curl_example_uses_an_editable_placeholder(client, pub_brand):
    """An invented numeric offer_id would 400 on first use and look like our
    bug; a visible slot tells the reader to substitute."""
    body = client.get(PUBLIC_TEXT, HTTP_HOST=HOST).content.decode()
    assert '"offer_id": <YOUR_OFFER_ID>' in body, 'placeholder should be unquoted, number-shaped'
    assert '"offer_id": 123' not in body


@pytest.mark.django_db
def test_conditional_required_note_is_derived_from_real_buyers(
        client, pub_brand, hypernet_route):
    body = client.get(PUBLIC_TEXT, HTTP_HOST=HOST).content.decode()
    assert 'some offers additionally require: country' in body


@pytest.mark.django_db
def test_no_conditional_note_when_no_buyer_demands_anything(client, pub_brand):
    body = client.get(PUBLIC_TEXT, HTTP_HOST=HOST).content.decode()
    assert 'additionally require' not in body


@pytest.mark.django_db
def test_page_is_shareable_but_not_indexable(client, pub_brand):
    body = client.get(PUBLIC_URL, HTTP_HOST=HOST).content.decode()
    assert 'noindex' in body


@pytest.mark.django_db
def test_brand_comes_from_the_host(client, pub_brand):
    other = Brand.objects.create(slug='other-host', name='OtherNet',
                                 primary_domain='other-host.test', is_default=False)
    # secure=True so the rendered base_url carries the scheme a real reader
    # would see; over plain http the doc would correctly say http://.
    body = client.get(PUBLIC_URL, HTTP_HOST='other-host.test', secure=True).content.decode()
    assert other.name in body
    assert f'https://{other.primary_domain}' in body
    assert pub_brand.name not in body, 'the host, not the default brand, decides'


# --- the OpenAPI schema link is withheld from the public variant --------------

@pytest.mark.django_db
@pytest.mark.parametrize('url', [PUBLIC_URL, PUBLIC_TEXT])
def test_public_doc_does_not_advertise_the_platform_schema(client, pub_brand, url):
    """/api/schema/ documents the WHOLE platform — 58 paths including
    /api/v1/admin/*, /network/*, the advertiser wallet and webhook management.
    Every one enforces auth (probed anonymously 2026-08-20: all 401), so linking
    it discloses no data — but it hands an unauthenticated reader a complete map
    of the admin surface, and tells a traffic source about capabilities that are
    none of their business. The five endpoints they need are already documented
    in full."""
    body = client.get(url, HTTP_HOST=HOST).content.decode()
    assert '/api/schema/' not in body
    assert 'OpenAPI' not in body


@pytest.mark.django_db
def test_the_private_doc_keeps_the_schema_link(client, pub_affiliate, pub_brand):
    """Withholding it publicly must not have removed it for a logged-in
    affiliate, who is a known party and may well want to generate a client."""
    client.force_login(pub_affiliate)
    body = client.get('/partner/api-docs/text/', HTTP_HOST=HOST).content.decode()
    assert '/api/schema/' in body
