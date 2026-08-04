"""Tests for leadgen/api_doc.py — the doc's single source of truth.

The point of most of these is anti-drift (spec §6.3): the doc must be
*derived* from the live backend, never hand-maintained alongside it. So they
assert the derivation itself — that every documented endpoint really is
routed, that a view opts in by declaring doc_purpose, that offer phase comes
from AffiliateOfferLink — rather than asserting a fixed expected payload,
which would just be the hand-maintained copy in another costume.
"""
import json

import pytest
from django.contrib.auth import get_user_model
from django.test import RequestFactory
from django.urls import resolve

from offer.models import Advertiser, Offer

from leadgen.api_doc import build_doc_context
from leadgen.models import AffiliateOfferLink

User = get_user_model()


@pytest.fixture
def approved_advertiser(db):
    user = User.objects.create_user(username='doc_adv', password='pass', email='docadv@test.com')
    return Advertiser.objects.create(
        user=user, company='DocAdvCo', email='docadv@test.com',
        advertiser_status=Advertiser.AdvertiserStatus.APPROVED, email_verified=True,
    )


@pytest.fixture
def doc_offer(db, approved_advertiser):
    """brand=None (platform-wide), so eligibility doesn't depend on
    Host-based brand resolution that RequestFactory can't perform."""
    return Offer.objects.create(
        title='Doc Offer', tracking_link='https://t.test/doc', advertiser=approved_advertiser)


def _doc(affiliate_user):
    request = RequestFactory().get('/partner/api-docs/')
    request.user = affiliate_user
    request.brand = None
    return build_doc_context(request, affiliate_user)


@pytest.mark.django_db
class TestEndpointsAreDerivedFromTheUrlConf:
    def test_every_documented_path_really_resolves(self, affiliate_user):
        """The anti-drift guarantee: a documented path can't be one that
        isn't wired, because it was read off the URL conf to begin with."""
        for endpoint in _doc(affiliate_user)['endpoints']:
            path = endpoint['path'].replace('<id>', '1')
            assert resolve(path), f'documented but unrouted: {path}'

    def test_documents_the_inbound_api(self, affiliate_user):
        by_path = {e['path']: e for e in _doc(affiliate_user)['endpoints']}
        assert by_path['/api/leads/submit']['method'] == 'POST'
        assert by_path['/api/leads']['method'] == 'GET'
        assert by_path['/api/leads/<id>']['method'] == 'GET'
        assert all(e['purpose'] for e in by_path.values())

    def test_a_view_without_doc_purpose_is_not_documented(self, affiliate_user):
        """leadgen also routes the public capture page, which affiliates have
        no business calling — opting in by declaring doc_purpose is what keeps
        it out."""
        paths = [e['path'] for e in _doc(affiliate_user)['endpoints']]
        assert not any(p.startswith('/l/') for p in paths)

    def test_a_newly_documented_view_appears_on_its_own(self, affiliate_user, monkeypatch):
        from leadgen.api_views import LeadStatusListView

        monkeypatch.setattr(LeadStatusListView, 'doc_purpose', 'Changed purpose.', raising=False)
        purposes = [e['purpose'] for e in _doc(affiliate_user)['endpoints']]
        assert 'Changed purpose.' in purposes


@pytest.mark.django_db
class TestOfferPhase:
    def test_offer_with_no_link_reads_as_testing(self, affiliate_user, doc_offer):
        """Spec §2.1 — a new integration is never born live, so the doc must
        not imply otherwise before the first lead is ever submitted."""
        row = next(o for o in _doc(affiliate_user)['offers'] if o['id'] == doc_offer.pk)
        assert row['phase'] == AffiliateOfferLink.PHASE_TESTING
        assert row['is_live'] is False
        assert row['started'] is False

    def test_live_link_is_reflected(self, affiliate_user, doc_offer):
        AffiliateOfferLink.objects.create(
            affiliate=affiliate_user, offer=doc_offer, phase=AffiliateOfferLink.PHASE_LIVE)
        row = next(o for o in _doc(affiliate_user)['offers'] if o['id'] == doc_offer.pk)
        assert row['phase'] == AffiliateOfferLink.PHASE_LIVE
        assert row['is_live'] is True
        assert row['started'] is True

    def test_another_affiliates_phase_does_not_leak(self, affiliate_user, doc_offer, db):
        other = User.objects.create_user(username='doc_other_aff', password='pass', email='o@test.com')
        AffiliateOfferLink.objects.create(
            affiliate=other, offer=doc_offer, phase=AffiliateOfferLink.PHASE_LIVE)
        row = next(o for o in _doc(affiliate_user)['offers'] if o['id'] == doc_offer.pk)
        assert row['phase'] == AffiliateOfferLink.PHASE_TESTING, 'read another affiliate\'s phase'


@pytest.mark.django_db
class TestErrorsAndExamples:
    def test_error_rows_quote_the_real_messages(self, affiliate_user):
        from leadgen.api_views import IsAffiliate

        errors = {e['status']: e for e in _doc(affiliate_user)['errors']}
        assert {400, 401, 403, 404, 429} <= set(errors)
        assert IsAffiliate.message in errors[403]['body']
        assert 'Invalid or inactive API key.' in errors[401]['body']

    def test_examples_use_a_real_approved_offer_id(self, affiliate_user, doc_offer):
        doc = _doc(affiliate_user)
        assert doc['examples']['offer_id_used'] == doc_offer.pk
        assert f'"offer_id": {doc_offer.pk}' in doc['examples']['single_curl']

    def test_examples_never_embed_a_live_secret(self, affiliate_user, affiliate_api_key):
        """The PDF and text exports are meant to be forwarded to a traffic
        source, so a real secret must not ride along in them."""
        doc = _doc(affiliate_user)
        assert affiliate_api_key.secret not in json.dumps(doc, default=str)
        assert 'YOUR_API_KEY_HERE' in doc['examples']['single_curl']

    def test_key_listing_is_ownership_scoped(self, affiliate_user, affiliate_api_key, db):
        from public_api.models import APIKey

        other = User.objects.create_user(username='doc_other_key', password='pass', email='k@test.com')
        APIKey.generate(user=other, name='Not yours')
        names = [k['name'] for k in _doc(affiliate_user)['keys']]
        assert names == [affiliate_api_key.name]


@pytest.mark.django_db
class TestNarrativeIsSharedNotForked:
    def test_narrative_travels_in_the_context(self, affiliate_user):
        """Every format renders this prose from here. If a renderer ever
        hardcodes its own copy again, the two will drift — which is exactly
        what happened to the testing→live explainer before this."""
        narrative = _doc(affiliate_user)['narrative']
        assert {'auth', 'testing_live', 'postbacks', 'pull', 'rate_limits'} <= set(narrative)
        assert all(isinstance(paras, list) and paras for paras in narrative.values())
