"""The ChainPulse integration, end to end, through the real endpoints.

This is the run the integrator is trying to get green: submit a lead with their
key, pull it back, see it convert to FTD, and find it again by both filters they
depend on. It drives the seed command rather than hand-built fixtures, so a
broken seed fails here instead of failing in the integrator's hands.

Negative cases are in the same file on purpose: "affiliate A can do X" is only
meaningful next to "affiliate B cannot".
"""
import pytest
from django.core.management import call_command
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from brands.models import Brand
from leadgen import canonical_status
from leadgen.models import Lead, LeadStatusEvent
from leadgen.status_sync import apply_status_change
from offer.models import Advertiser, Offer
from public_api.models import APIKey
from user_profile.models import Profile

User = get_user_model()

SUBMIT_URL = '/api/leads/submit'
LIST_URL = '/api/leads'


@pytest.fixture
def seeded(db, settings):
    """Run the real seed command, then hand back what it made."""
    settings.DEBUG = True  # the command refuses to run production-like without --force
    call_command('seed_chainpulse', verbosity=0)

    brand = Brand.objects.get(slug='chainpulse')
    affiliate = User.objects.get(username='chainpulse_demo_affiliate')
    offer = Offer.objects.get(title='ChainPulse Demo Offer')
    key = APIKey.objects.filter(user=affiliate, is_active=True).first()
    return brand, affiliate, offer, key


def _client(key):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f'ApiKey {key.secret}')
    return client


@pytest.mark.django_db
class TestSeedIsIdempotent:
    def test_running_twice_creates_no_duplicates(self, seeded, settings):
        settings.DEBUG = True
        before = (Brand.objects.filter(slug='chainpulse').count(),
                  Offer.objects.filter(title='ChainPulse Demo Offer').count(),
                  User.objects.filter(username='chainpulse_demo_affiliate').count())

        call_command('seed_chainpulse', verbosity=0)

        after = (Brand.objects.filter(slug='chainpulse').count(),
                 Offer.objects.filter(title='ChainPulse Demo Offer').count(),
                 User.objects.filter(username='chainpulse_demo_affiliate').count())
        assert before == after == (1, 1, 1)

    def test_rerun_does_not_rotate_the_key(self, seeded, settings):
        """A second run must not break a working integration."""
        _brand, affiliate, _offer, key = seeded
        original = key.secret
        settings.DEBUG = True
        call_command('seed_chainpulse', verbosity=0)
        key.refresh_from_db()
        assert key.secret == original

    def test_refuses_to_run_production_like_without_force(self, db, settings):
        from django.core.management.base import CommandError

        settings.DEBUG = False
        with pytest.raises(CommandError, match='--force'):
            call_command('seed_chainpulse', verbosity=0)


@pytest.mark.django_db
class TestChainPulseEndToEnd:
    def test_submit_pull_convert_repull(self, seeded):
        _brand, affiliate, offer, key = seeded
        client = _client(key)

        # 1. Submit -> 201
        resp = client.post(SUBMIT_URL, {
            'email': 'consumer@chainpulse.invalid', 'phone': '+15551230001',
            'offer_id': offer.pk, 'source_id': 'cp-e2e-1',
        }, format='json')
        assert resp.status_code == 201, resp.data
        lead_id = resp.data['id']

        # 2. Pull it back
        resp = client.get(LIST_URL)
        assert resp.status_code == 200
        assert lead_id in [r['id'] for r in resp.data['results']]

        # 3. Convert to FTD through the production path
        cutoff = timezone.now()
        lead = Lead.objects.get(pk=lead_id)
        apply_status_change(lead, canonical_status.FTD, source=LeadStatusEvent.SOURCE_OPERATOR)

        # 4a. Re-pull by status
        resp = client.get(LIST_URL, {'status': canonical_status.FTD})
        assert resp.status_code == 200
        assert [r['id'] for r in resp.data['results']] == [lead_id]

        # 4b. Re-pull by updated_since — the reconcile cursor
        resp = client.get(LIST_URL, {'updated_since': cutoff.isoformat()})
        assert resp.status_code == 200, resp.data
        assert lead_id in [r['id'] for r in resp.data['results']], \
            'the FTD conversion was invisible to an updated_since poll'

    def test_bad_offer_id_returns_the_documented_400(self, seeded):
        _brand, _affiliate, _offer, key = seeded
        resp = _client(key).post(SUBMIT_URL, {
            'email': 'bad@chainpulse.invalid', 'phone': '+15551230002',
            'offer_id': 99999999,
        }, format='json')
        assert resp.status_code == 400
        assert 'does not resolve to an offer you can send to' in str(resp.data)


@pytest.mark.django_db
class TestCrossBrandIsolation:
    """A ChainPulse offer and lead must be invisible and unusable to another
    brand's affiliate."""

    @pytest.fixture
    def outsider(self, db):
        brand = Brand.objects.create(
            name='Outsider', slug='cp-outsider', primary_domain='outsider.test',
            tracking_domain='t.outsider.test', is_default=False)
        user = User.objects.create_user(username='cp_outsider_aff', password='pass')
        p = user.profile
        p.role = Profile.Role.AFFILIATE
        p.affiliate_status = Profile.AffiliateStatus.APPROVED
        p.email_verified = True
        p.brand = brand
        p.save()
        # Give them a real offer of their own, so a failure below is about
        # scoping rather than about having no offers at all.
        adv_user = User.objects.create_user(username='cp_outsider_adv', password='pass')
        adv = Advertiser.objects.create(
            user=adv_user, brand=brand, company='OutsiderCo', email='o@t.invalid',
            advertiser_status=Advertiser.AdvertiserStatus.APPROVED, email_verified=True)
        Offer.objects.create(
            title='Outsider Offer', brand=brand, advertiser=adv,
            tracking_link='https://t.outsider.test/click', status='Active')
        return user, APIKey.generate(user=user, name='outsider key')

    def test_outsider_cannot_submit_to_the_chainpulse_offer(self, seeded, outsider):
        _brand, _affiliate, offer, _key = seeded
        _user, outsider_key = outsider
        resp = _client(outsider_key).post(SUBMIT_URL, {
            'email': 'x@outsider.test', 'phone': '+15559990001', 'offer_id': offer.pk,
        }, format='json')
        assert resp.status_code == 400
        assert 'does not resolve' in str(resp.data)

    def test_outsider_cannot_see_the_chainpulse_offer_in_their_doc(self, seeded, outsider):
        from django.test import RequestFactory

        from leadgen.api_doc import build_doc_context

        _brand, _affiliate, offer, _key = seeded
        user, _k = outsider
        request = RequestFactory().get('/partner/api-docs/')
        request.user = user
        doc = build_doc_context(request, user)
        assert offer.pk not in [o['id'] for o in doc['offers']]
        assert 'ChainPulse Demo Offer' not in str(doc['offers'])

    def test_outsider_cannot_pull_a_chainpulse_lead(self, seeded, outsider):
        _brand, affiliate, offer, key = seeded
        _user, outsider_key = outsider

        submitted = _client(key).post(SUBMIT_URL, {
            'email': 'private@chainpulse.invalid', 'phone': '+15551230003',
            'offer_id': offer.pk,
        }, format='json')
        lead_id = submitted.data['id']

        # 404, not 403: existence is not confirmed to another tenant.
        detail = _client(outsider_key).get(f'{LIST_URL}/{lead_id}')
        assert detail.status_code == 404
        listing = _client(outsider_key).get(LIST_URL)
        assert lead_id not in [r['id'] for r in listing.data['results']]
