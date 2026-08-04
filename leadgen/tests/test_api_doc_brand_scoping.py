"""The doc must describe the affiliate's OWN integration, whichever brand
domain they reached the portal through.

Why this file exists: BrandMiddleware resolves request.brand from the Host
header and falls back to the default brand when it doesn't match, and login is
not brand-gated. So a Thika affiliate who reaches the Nexora domain has
request.brand = Nexora. Building the doc from the request therefore produced a
document showing Nexora's host and, far worse, **Nexora's offers with their
offer_ids** — embedded in the curl examples an affiliate forwards to their
traffic source. That is cross-tenant data exposure, not a cosmetic bug, and
the offer-list assertions below are the ones that prove it is closed. Asserting
only the host would leave the dangerous half unverified.

Scope: this fixes the doc. BrandMiddleware's cross-brand fallback is
deliberately left alone — a separate, platform-wide decision.
"""
import json

import pytest
from django.contrib.auth import get_user_model
from django.test import RequestFactory

from brands.models import Brand
from offer.models import Advertiser, Offer
from user_profile.models import Profile

from leadgen.api_doc import build_doc_context

User = get_user_model()


@pytest.fixture
def advertiser(db):
    user = User.objects.create_user(username='scope_adv', password='pass', email='scope@test.com')
    return Advertiser.objects.create(
        user=user, company='ScopeAdv', email='scope@test.com',
        advertiser_status=Advertiser.AdvertiserStatus.APPROVED, email_verified=True)


@pytest.fixture
def brands(db):
    """Three tenants: Nexora is the default, so it is also what an unmatched
    Host falls back to — the exact condition that caused the leak."""
    return {
        'nexora': Brand.objects.create(
            name='Nexora', slug='scope-nexora', primary_domain='cpa.nexora.test',
            tracking_domain='t.nexora.test', is_default=True),
        'thika': Brand.objects.create(
            name='Thika', slug='scope-thika', primary_domain='partners.thika.test',
            tracking_domain='t.thika.test', is_default=False),
        'ccs': Brand.objects.create(
            name='CCS', slug='scope-ccs', primary_domain='partners.ccs.test',
            tracking_domain='t.ccs.test', is_default=False),
    }


@pytest.fixture
def offers(db, brands, advertiser):
    return {
        key: Offer.objects.create(
            title=f'{key.upper()} ONLY OFFER', tracking_link=f'https://t.test/{key}',
            brand=brand, advertiser=advertiser)
        for key, brand in brands.items()
    }


def _affiliate(username, brand):
    user = User.objects.create_user(username=username, password='pass')
    user.profile.role = Profile.Role.AFFILIATE
    user.profile.affiliate_status = Profile.AffiliateStatus.APPROVED
    user.profile.email_verified = True
    user.profile.brand = brand
    user.profile.save()
    return user


def _doc_reached_via(affiliate, host, request_brand):
    """Build the doc as if the affiliate reached the portal on `host`.
    request.brand is set to what BrandMiddleware would have resolved."""
    request = RequestFactory().get('/partner/api-docs/', HTTP_HOST=host)
    request.user = affiliate
    request.brand = request_brand
    return build_doc_context(request, affiliate)


@pytest.mark.django_db
class TestDocFollowsTheAffiliatesOwnBrand:
    def test_thika_affiliate_on_nexora_domain_gets_thika_doc(self, brands, offers):
        """THE reproduction case. Was: Nexora host + Nexora offer_ids."""
        affiliate = _affiliate('thika_aff', brands['thika'])
        doc = _doc_reached_via(affiliate, 'cpa.nexora.test', brands['nexora'])

        assert doc['base_url'] == 'http://partners.thika.test'
        titles = [o['title'] for o in doc['offers']]
        assert titles == ['THIKA ONLY OFFER'], titles
        assert 'NEXORA ONLY OFFER' not in titles, 'leaked another brand\'s offer'
        # The offer_id that rides in the copy-paste curl example must be theirs.
        assert doc['examples']['offer_id_used'] == offers['thika'].pk

    def test_ccs_affiliate_on_nexora_domain_gets_ccs_doc(self, brands, offers):
        affiliate = _affiliate('ccs_aff', brands['ccs'])
        doc = _doc_reached_via(affiliate, 'cpa.nexora.test', brands['nexora'])

        assert doc['base_url'] == 'http://partners.ccs.test'
        titles = [o['title'] for o in doc['offers']]
        assert titles == ['CCS ONLY OFFER'], titles
        assert doc['examples']['offer_id_used'] == offers['ccs'].pk

    def test_thika_affiliate_on_ccs_domain_gets_thika_doc(self, brands, offers):
        """Not just the default-brand fallback — any foreign host."""
        affiliate = _affiliate('thika_aff2', brands['thika'])
        doc = _doc_reached_via(affiliate, 'partners.ccs.test', brands['ccs'])

        assert doc['base_url'] == 'http://partners.thika.test'
        assert [o['title'] for o in doc['offers']] == ['THIKA ONLY OFFER']

    def test_nexora_affiliate_unaffected(self, brands, offers):
        """No regression for the common single-brand case."""
        affiliate = _affiliate('nexora_aff', brands['nexora'])
        doc = _doc_reached_via(affiliate, 'cpa.nexora.test', brands['nexora'])

        assert doc['base_url'] == 'http://cpa.nexora.test'
        assert [o['title'] for o in doc['offers']] == ['NEXORA ONLY OFFER']

    def test_no_foreign_brand_data_anywhere_in_the_context(self, brands, offers):
        """Belt and braces: scan the whole serialized doc, not just the fields
        we thought to check — the curl examples, the postback rows, all of it."""
        affiliate = _affiliate('thika_aff3', brands['thika'])
        doc = _doc_reached_via(affiliate, 'cpa.nexora.test', brands['nexora'])
        blob = json.dumps(doc, default=str)

        assert 'cpa.nexora.test' not in blob
        assert 'partners.ccs.test' not in blob
        assert 'NEXORA ONLY OFFER' not in blob
        assert 'CCS ONLY OFFER' not in blob
        assert str(offers['nexora'].pk) not in [str(o['id']) for o in doc['offers']]

    def test_unbranded_offers_still_reach_everyone(self, brands, advertiser):
        """Brand isolation must not break the legacy/network-wide case."""
        Offer.objects.create(
            title='NETWORK WIDE OFFER', tracking_link='https://t.test/nw',
            brand=None, advertiser=advertiser)
        affiliate = _affiliate('thika_aff4', brands['thika'])
        doc = _doc_reached_via(affiliate, 'cpa.nexora.test', brands['nexora'])

        assert 'NETWORK WIDE OFFER' in [o['title'] for o in doc['offers']]

    def test_affiliate_without_a_brand_falls_back_to_the_request_host(self, brands, offers):
        """A profile with no brand (legacy rows) must still produce a usable
        doc rather than crashing — the same fallback admin_views uses."""
        affiliate = _affiliate('brandless_aff', None)
        doc = _doc_reached_via(affiliate, 'cpa.nexora.test', brands['nexora'])

        assert doc['base_url'] == 'http://cpa.nexora.test'


@pytest.mark.django_db
class TestOwnershipAcrossAffiliates:
    def test_one_affiliates_doc_never_shows_anothers_brand_or_offers(self, brands, offers):
        thika_aff = _affiliate('own_thika', brands['thika'])
        ccs_aff = _affiliate('own_ccs', brands['ccs'])

        thika_doc = _doc_reached_via(thika_aff, 'cpa.nexora.test', brands['nexora'])
        ccs_doc = _doc_reached_via(ccs_aff, 'cpa.nexora.test', brands['nexora'])

        assert thika_doc['base_url'] != ccs_doc['base_url']
        assert [o['title'] for o in thika_doc['offers']] == ['THIKA ONLY OFFER']
        assert [o['title'] for o in ccs_doc['offers']] == ['CCS ONLY OFFER']
        assert thika_doc['examples']['offer_id_used'] != ccs_doc['examples']['offer_id_used']
