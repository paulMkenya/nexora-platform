"""A lead must land in ITS OWN tenant, whatever host it was submitted to.

THE BUG (found 2026-08-20, confirmed in production data). _create_lead stamped
Lead.brand from `request.brand`, which BrandMiddleware derives from the HOST
HEADER, falling back to the default brand when no domain matches. The inbound
API is authenticated by API key and is not host-gated, so that value is
accident- and attacker-controlled.

Lead.brand is what leadgen.routing.resolve_buyer_chain filters rules on. A
mis-stamped lead was therefore routed by ANOTHER TENANT'S rules to ANOTHER
TENANT'S buyer — consumer PII across the tenant boundary, revenue attributed to
the wrong brand, and the lead invisible in its real owner's brand-scoped
console.

services.start_injection's cross-brand guard does not catch this: it compares
lead.brand_id to buyer.brand_id, and by then both agree on the WRONG brand. It
exists to stop a RULE reaching across brands, not a lead mis-stamped before
routing ran. That is why the assertions here are about Lead.brand and the
resolved chain, not about the guard.

Real occurrence: lead 28 (2026-08-06) — ChainPulse affiliate, ChainPulse offer,
landed in brand 6. Never delivered only because that brand's one buyer had
auto_inject off. Luck, not design.
"""
import pytest
from django.contrib.auth import get_user_model

from brands.models import Brand
from leadgen.models import BoxType, Lead, LeadBuyer, RoutingRule
from leadgen.routing import resolve_buyer_chain
from offer.models import Advertiser, Offer
from public_api.models import APIKey
from user_profile.models import Profile

User = get_user_model()

SUBMIT_URL = '/api/leads/submit'


@pytest.fixture
def tenant_a(db):
    return Brand.objects.create(
        slug='iso-tenant-a', name='Tenant A', primary_domain='iso-a.test',
        tracking_domain='t.iso-a.test', is_default=False)


@pytest.fixture
def tenant_b(db):
    """Deliberately BOTH a real host and the default brand, so this one fixture
    covers the two ways request.brand goes wrong: a deliberate post to another
    tenant's domain, and the silent fallback for any unrecognised host."""
    return Brand.objects.create(
        slug='iso-tenant-b', name='Tenant B', primary_domain='iso-b.test',
        tracking_domain='t.iso-b.test', is_default=True)


@pytest.fixture
def affiliate_of_a(db, tenant_a):
    u = User.objects.create_user(username='iso_aff_a', password='x', email='iso-a@test.test')
    u.profile.role = Profile.Role.AFFILIATE
    u.profile.brand = tenant_a
    u.profile.affiliate_status = Profile.AffiliateStatus.APPROVED
    u.profile.email_verified = True
    u.profile.save()
    return u


@pytest.fixture
def offer_of_a(db, tenant_a):
    adv_user = User.objects.create_user(username='iso_adv_a', password='x')
    advertiser = Advertiser.objects.create(
        user=adv_user, brand=tenant_a, company='IsoACo', email='iso-adv@a.test',
        advertiser_status=Advertiser.AdvertiserStatus.APPROVED, email_verified=True)
    return Offer.objects.create(
        title='Iso A Offer', tracking_link='https://t.iso-a.test/c',
        brand=tenant_a, advertiser=advertiser)


@pytest.fixture
def buyer_of_b(db, tenant_b):
    """Tenant B's buyer, with a wildcard rule — the destination a mis-stamped
    lead used to resolve to."""
    bt = BoxType.objects.create(
        name='Iso BT', slug='iso-bt', connector_class='leadgen.connectors.LeadBuyerConnector',
        auth_type=BoxType.AUTH_API_KEY_QUERY, auth_param_name='apiKey',
        single_endpoint_path='/leads', batch_endpoint_path='', fetch_endpoint_path='/leads',
        batch_max_size=1)
    b = LeadBuyer.objects.create(
        brand=tenant_b, box_type=bt, name='B Buyer', slug='iso-b-buyer',
        is_active=True, auto_inject=False, base_url='https://iso-b-buyer.test')
    b.set_api_key('k')
    b.save(update_fields=['api_key_encrypted'])
    RoutingRule.objects.create(brand=tenant_b, buyer=b, priority=100, is_active=True)
    return b


def _submit(client, affiliate, offer, host):
    key = APIKey.generate(user=affiliate, name=f'iso-{host}', requests_per_hour=1000)
    return client.post(
        SUBMIT_URL,
        data={'offer_id': offer.pk, 'first_name': 'X', 'last_name': 'Y',
              'email': f'x-{host}@y.test', 'phone': '+15551230000',
              'source_id': f'iso-{host}', 'country': 'US'},
        content_type='application/json',
        HTTP_HOST=host,
        HTTP_AUTHORIZATION=f'ApiKey {key.secret}')


@pytest.mark.django_db
@pytest.mark.parametrize('host', [
    'iso-b.test',      # another tenant's real domain
    'nonsense.test',   # unrecognised -> BrandMiddleware falls back to the default
    '203.0.113.7',     # a bare IP, e.g. a misconfigured integration
])
def test_lead_belongs_to_its_own_tenant_whatever_the_host(
        client, affiliate_of_a, offer_of_a, tenant_a, tenant_b, buyer_of_b, host):
    resp = _submit(client, affiliate_of_a, offer_of_a, host)
    assert resp.status_code == 201
    lead = Lead.objects.get(pk=resp.json()['id'])
    assert lead.brand_id == tenant_a.pk, (
        f'lead submitted to {host!r} landed in brand {lead.brand_id}, not its own {tenant_a.pk}')


@pytest.mark.django_db
def test_mis_hosted_lead_is_not_routed_by_another_tenants_rules(
        client, affiliate_of_a, offer_of_a, tenant_a, tenant_b, buyer_of_b):
    """The consequence that actually costs money: tenant B's wildcard rule must
    never pick up tenant A's lead."""
    resp = _submit(client, affiliate_of_a, offer_of_a, 'iso-b.test')
    lead = Lead.objects.get(pk=resp.json()['id'])
    assert resolve_buyer_chain(lead) == [], (
        'tenant A has no rules, so its lead must route NOWHERE — resolving to '
        "tenant B's buyer would deliver another tenant's traffic")


@pytest.mark.django_db
def test_the_offer_gate_still_blocks_another_tenants_offer(
        client, affiliate_of_a, tenant_a, tenant_b):
    """Sanity check on the layer this fix relies on: offer.brand is only a safe
    source for the lead's brand because _resolve_offer already refuses an offer
    outside the affiliate's own brand."""
    adv_user = User.objects.create_user(username='iso_adv_b', password='x')
    advertiser = Advertiser.objects.create(
        user=adv_user, brand=tenant_b, company='IsoBCo', email='iso-adv@b.test',
        advertiser_status=Advertiser.AdvertiserStatus.APPROVED, email_verified=True)
    offer_of_b = Offer.objects.create(
        title='Iso B Offer', tracking_link='https://t.iso-b.test/c',
        brand=tenant_b, advertiser=advertiser)

    resp = _submit(client, affiliate_of_a, offer_of_b, 'iso-b.test')
    assert resp.status_code == 400
    assert resp.json() == {'detail': 'offer_id does not resolve to an offer you can send to.'}
