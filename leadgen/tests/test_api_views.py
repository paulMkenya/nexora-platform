"""Tests for the inbound affiliate lead API (leadgen/api_views.py) — auth
(reused public_api.APIKey scheme), role gating, validation, the batch
partial-success envelope, offer_id eligibility, idempotency, and the pull
API (list/detail/statuses) — Affiliate Inbound API spec §4/§5.2."""
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from leadgen import canonical_status
from leadgen.models import Lead

SUBMIT_URL = '/api/leads/submit'
BATCH_URL = '/api/leads/submit/batch'
LIST_URL = '/api/leads'
STATUSES_URL = '/api/leads/statuses'


def _client_with_key(key):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f'ApiKey {key.secret}')
    return client


@pytest.fixture
def eligible_offer(db):
    """A standalone Offer with an APPROVED+verified advertiser — the `offer`
    fixture's advertiser starts PENDING/unverified (the real onboarding
    default — see brands/tests/test_advertiser_onboarding.py) so it does NOT
    pass affiliate_ui._eligible_offers' gating out of the box. Deliberately
    NOT built on top of the shared `offer`/`advertiser` fixtures — a few
    tests need both a genuinely-eligible AND a genuinely-ineligible offer in
    the same test, and mutating the shared one in place would make both
    fixtures resolve to the same row (pytest caches fixtures per test).
    brand=None (platform-wide) sidesteps request.brand-detection entirely —
    a bare APIClient() test call has no real Host-based brand resolution."""
    from django.contrib.auth import get_user_model

    from offer.models import Advertiser, Offer

    User = get_user_model()
    user = User.objects.create_user(username='eligible_offer_advertiser', password='pass')
    advertiser = Advertiser.objects.create(
        user=user, company='EligibleCo', email='eligible-advertiser@test.com',
        advertiser_status=Advertiser.AdvertiserStatus.APPROVED, email_verified=True,
    )
    return Offer.objects.create(
        title='Eligible Test Offer', tracking_link='https://t.leadgen.test/eligible-click',
        brand=None, advertiser=advertiser,
    )


@pytest.mark.django_db
class TestAuthAndPermissions:
    def test_missing_auth_returns_401(self):
        client = APIClient()
        resp = client.post(SUBMIT_URL, {'email': 'a@test.com', 'phone': '+15551234567'})
        assert resp.status_code == 401

    def test_invalid_key_returns_401(self):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION='ApiKey not-a-real-key')
        resp = client.post(SUBMIT_URL, {'email': 'a@test.com', 'phone': '+15551234567'})
        assert resp.status_code == 401

    def test_non_affiliate_key_returns_403(self, advertiser_api_key):
        client = _client_with_key(advertiser_api_key)
        resp = client.post(SUBMIT_URL, {'email': 'a@test.com', 'phone': '+15551234567'})
        assert resp.status_code == 403

    def test_valid_affiliate_key_authenticates(self, affiliate_api_key, eligible_offer):
        client = _client_with_key(affiliate_api_key)
        with patch('leadgen.api_views.maybe_auto_inject'):
            resp = client.post(SUBMIT_URL, {
                'email': 'a@test.com', 'phone': '+15551234567', 'offer_id': eligible_offer.pk,
            }, format='json')
        assert resp.status_code == 201


@pytest.mark.django_db
class TestSubmitValidation:
    def test_missing_email_returns_400(self, affiliate_api_key, eligible_offer):
        client = _client_with_key(affiliate_api_key)
        resp = client.post(SUBMIT_URL, {'phone': '+15551234567', 'offer_id': eligible_offer.pk}, format='json')
        assert resp.status_code == 400
        assert 'email' in resp.data

    def test_missing_phone_returns_400(self, affiliate_api_key, eligible_offer):
        client = _client_with_key(affiliate_api_key)
        resp = client.post(SUBMIT_URL, {'email': 'a@test.com', 'offer_id': eligible_offer.pk}, format='json')
        assert resp.status_code == 400
        assert 'phone' in resp.data

    def test_invalid_phone_format_returns_400(self, affiliate_api_key, eligible_offer):
        client = _client_with_key(affiliate_api_key)
        resp = client.post(SUBMIT_URL, {
            'email': 'a@test.com', 'phone': 'not-a-phone', 'offer_id': eligible_offer.pk,
        }, format='json')
        assert resp.status_code == 400
        assert 'phone' in resp.data

    def test_missing_offer_id_returns_400(self, affiliate_api_key):
        client = _client_with_key(affiliate_api_key)
        resp = client.post(SUBMIT_URL, {'email': 'a@test.com', 'phone': '+15551234567'}, format='json')
        assert resp.status_code == 400
        assert 'offer_id' in resp.data

    def test_offer_id_not_eligible_returns_400(self, affiliate_api_key, offer):
        """`offer` (unlike `eligible_offer`) still has its default PENDING/
        unverified advertiser — must be rejected exactly like a nonexistent
        offer_id, never a 500 and never silently accepted."""
        client = _client_with_key(affiliate_api_key)
        resp = client.post(SUBMIT_URL, {
            'email': 'a@test.com', 'phone': '+15551234567', 'offer_id': offer.pk,
        }, format='json')
        assert resp.status_code == 400
        assert 'offer_id' in str(resp.data).lower() or 'offer' in str(resp.data).lower()

    def test_offer_id_nonexistent_returns_400(self, affiliate_api_key):
        client = _client_with_key(affiliate_api_key)
        resp = client.post(SUBMIT_URL, {
            'email': 'a@test.com', 'phone': '+15551234567', 'offer_id': 999999,
        }, format='json')
        assert resp.status_code == 400

    def test_valid_submission_creates_lead_with_correct_channel(self, affiliate_api_key, affiliate_user, eligible_offer):
        client = _client_with_key(affiliate_api_key)
        with patch('leadgen.api_views.maybe_auto_inject'):
            resp = client.post(SUBMIT_URL, {
                'first_name': 'Jane', 'last_name': 'Doe',
                'email': 'jane@test.com', 'phone': '+15551234567', 'vertical': 'crypto',
                'offer_id': eligible_offer.pk,
            }, format='json')
        assert resp.status_code == 201
        lead = Lead.objects.get(email='jane@test.com')
        assert lead.intake_channel == Lead.CHANNEL_AFFILIATE_API
        assert lead.affiliate_id == affiliate_user.pk
        assert lead.offer_id == eligible_offer.pk
        assert lead.vertical == 'crypto'
        assert lead.status == Lead.STATUS_NEW

    def test_submission_triggers_maybe_auto_inject(self, affiliate_api_key, eligible_offer):
        client = _client_with_key(affiliate_api_key)
        with patch('leadgen.api_views.maybe_auto_inject') as mock_inject:
            client.post(SUBMIT_URL, {
                'email': 'a@test.com', 'phone': '+15551234567', 'offer_id': eligible_offer.pk,
            }, format='json')
        mock_inject.assert_called_once()

    def test_country_ip_user_agent_sub_ids_round_trip(self, affiliate_api_key, eligible_offer):
        client = _client_with_key(affiliate_api_key)
        with patch('leadgen.api_views.maybe_auto_inject'):
            resp = client.post(SUBMIT_URL, {
                'email': 'sub@test.com', 'phone': '+15551234567', 'offer_id': eligible_offer.pk,
                'country': 'us', 'ip': '203.0.113.5', 'user_agent': 'Mozilla/5.0 TestAgent',
                'sub1': 'campaign-a', 'sub2': 'creative-b',
            }, format='json')
        assert resp.status_code == 201
        lead = Lead.objects.get(email='sub@test.com')
        assert lead.country_iso2 == 'US'  # uppercased
        assert lead.ip == '203.0.113.5'
        assert lead.user_agent == 'Mozilla/5.0 TestAgent'
        assert resp.data['sub1'] == 'campaign-a'
        assert resp.data['sub2'] == 'creative-b'
        assert resp.data['sub3'] == ''


@pytest.mark.django_db
class TestIdempotency:
    def test_same_source_id_returns_original_lead_not_a_new_one(self, affiliate_api_key, eligible_offer):
        client = _client_with_key(affiliate_api_key)
        payload = {
            'email': 'retry@test.com', 'phone': '+15551234567', 'offer_id': eligible_offer.pk,
            'source_id': 'aff-tracking-123',
        }
        with patch('leadgen.api_views.maybe_auto_inject'):
            first = client.post(SUBMIT_URL, payload, format='json')
            second = client.post(SUBMIT_URL, payload, format='json')
        assert first.status_code == 201
        assert second.status_code == 200  # not 201 — no new row
        assert first.data['id'] == second.data['id']
        assert Lead.objects.filter(email='retry@test.com').count() == 1

    def test_same_phone_and_email_within_window_without_source_id_dedupes(self, affiliate_api_key, eligible_offer):
        client = _client_with_key(affiliate_api_key)
        payload = {'email': 'nodupe@test.com', 'phone': '+15559990000', 'offer_id': eligible_offer.pk}
        with patch('leadgen.api_views.maybe_auto_inject'):
            first = client.post(SUBMIT_URL, payload, format='json')
            second = client.post(SUBMIT_URL, payload, format='json')
        assert second.status_code == 200
        assert first.data['id'] == second.data['id']

    def test_different_source_id_is_a_genuinely_new_lead(self, affiliate_api_key, eligible_offer):
        client = _client_with_key(affiliate_api_key)
        with patch('leadgen.api_views.maybe_auto_inject'):
            first = client.post(SUBMIT_URL, {
                'email': 'multi@test.com', 'phone': '+15551112222', 'offer_id': eligible_offer.pk,
                'source_id': 'sub-1',
            }, format='json')
            second = client.post(SUBMIT_URL, {
                'email': 'multi@test.com', 'phone': '+15551112222', 'offer_id': eligible_offer.pk,
                'source_id': 'sub-2',
            }, format='json')
        assert first.status_code == 201
        assert second.status_code == 201
        assert first.data['id'] != second.data['id']


@pytest.mark.django_db
class TestBatchSubmit:
    def test_empty_list_returns_400(self, affiliate_api_key):
        client = _client_with_key(affiliate_api_key)
        resp = client.post(BATCH_URL, {'leads': []}, format='json')
        assert resp.status_code == 400

    def test_non_list_returns_400(self, affiliate_api_key):
        client = _client_with_key(affiliate_api_key)
        resp = client.post(BATCH_URL, {'leads': 'not-a-list'}, format='json')
        assert resp.status_code == 400

    def test_over_max_batch_size_returns_400(self, affiliate_api_key, eligible_offer):
        client = _client_with_key(affiliate_api_key)
        items = [{'email': f'x{i}@test.com', 'phone': '+15551234567', 'offer_id': eligible_offer.pk}
                  for i in range(201)]
        resp = client.post(BATCH_URL, {'leads': items}, format='json')
        assert resp.status_code == 400

    def test_partial_success_envelope(self, affiliate_api_key, eligible_offer):
        client = _client_with_key(affiliate_api_key)
        items = [
            {'email': 'good@test.com', 'phone': '+15551234567', 'offer_id': eligible_offer.pk},
            {'email': 'bad@test.com', 'phone': 'not-a-phone', 'offer_id': eligible_offer.pk},
        ]
        with patch('leadgen.api_views.maybe_auto_inject'):
            resp = client.post(BATCH_URL, {'leads': items}, format='json')
        assert resp.status_code == 201
        assert len(resp.data['addedLeads']) == 1
        assert len(resp.data['failedToAddLeads']) == 1
        assert resp.data['addedLeads'][0]['email'] == 'good@test.com'

    def test_ineligible_offer_id_fails_that_item_only(self, affiliate_api_key, eligible_offer, offer):
        client = _client_with_key(affiliate_api_key)
        items = [
            {'email': 'ok@test.com', 'phone': '+15551234567', 'offer_id': eligible_offer.pk},
            {'email': 'badoffer@test.com', 'phone': '+15551234567', 'offer_id': offer.pk},
        ]
        with patch('leadgen.api_views.maybe_auto_inject'):
            resp = client.post(BATCH_URL, {'leads': items}, format='json')
        assert resp.status_code == 201
        assert len(resp.data['addedLeads']) == 1
        assert len(resp.data['failedToAddLeads']) == 1

    def test_all_failed_returns_400(self, affiliate_api_key, eligible_offer):
        client = _client_with_key(affiliate_api_key)
        items = [{'email': 'bad@test.com', 'phone': 'not-a-phone', 'offer_id': eligible_offer.pk}]
        resp = client.post(BATCH_URL, {'leads': items}, format='json')
        assert resp.status_code == 400
        assert len(resp.data['failedToAddLeads']) == 1


@pytest.mark.django_db
class TestListLeads:
    def test_returns_only_calling_affiliates_own_leads(self, affiliate_api_key, affiliate_user, brand):
        from django.contrib.auth import get_user_model
        from user_profile.models import Profile
        User = get_user_model()

        other = User.objects.create_user(username='other_affiliate', password='pass')
        other.profile.role = Profile.Role.AFFILIATE
        other.profile.save(update_fields=['role'])

        Lead.objects.create(
            intake_channel=Lead.CHANNEL_AFFILIATE_API, affiliate=affiliate_user,
            email='mine@test.com', phone='+15551234567',
        )
        Lead.objects.create(
            intake_channel=Lead.CHANNEL_AFFILIATE_API, affiliate=other,
            email='not-mine@test.com', phone='+15551234567',
        )

        client = _client_with_key(affiliate_api_key)
        resp = client.get(LIST_URL)
        assert resp.status_code == 200
        emails = [l['email'] for l in resp.data['results']]
        assert 'mine@test.com' in emails
        assert 'not-mine@test.com' not in emails

    def test_response_is_paginated(self, affiliate_api_key, affiliate_user):
        for i in range(3):
            Lead.objects.create(
                intake_channel=Lead.CHANNEL_AFFILIATE_API, affiliate=affiliate_user,
                email=f'page{i}@test.com', phone='+15551234567',
            )
        client = _client_with_key(affiliate_api_key)
        resp = client.get(LIST_URL, {'page_size': 2})
        assert resp.status_code == 200
        assert resp.data['count'] == 3
        assert len(resp.data['results']) == 2
        assert resp.data['next'] is not None

    def test_filter_by_source_id(self, affiliate_api_key, affiliate_user):
        Lead.objects.create(
            intake_channel=Lead.CHANNEL_AFFILIATE_API, affiliate=affiliate_user,
            email='a@test.com', phone='+15551234567', source_id='wanted',
        )
        Lead.objects.create(
            intake_channel=Lead.CHANNEL_AFFILIATE_API, affiliate=affiliate_user,
            email='b@test.com', phone='+15551234567', source_id='other',
        )
        client = _client_with_key(affiliate_api_key)
        resp = client.get(LIST_URL, {'source_id': 'wanted'})
        emails = [l['email'] for l in resp.data['results']]
        assert emails == ['a@test.com']

    def test_filter_by_status(self, affiliate_api_key, affiliate_user):
        applied = Lead.objects.create(
            intake_channel=Lead.CHANNEL_AFFILIATE_API, affiliate=affiliate_user,
            email='ftd@test.com', phone='+15551234567',
        )
        Lead.objects.filter(pk=applied.pk).update(canonical_status=canonical_status.FTD)
        Lead.objects.create(
            intake_channel=Lead.CHANNEL_AFFILIATE_API, affiliate=affiliate_user,
            email='new@test.com', phone='+15551234567',
        )
        client = _client_with_key(affiliate_api_key)
        resp = client.get(LIST_URL, {'status': canonical_status.FTD})
        emails = [l['email'] for l in resp.data['results']]
        assert emails == ['ftd@test.com']

    def test_filter_by_updated_since(self, affiliate_api_key, affiliate_user):
        old = Lead.objects.create(
            intake_channel=Lead.CHANNEL_AFFILIATE_API, affiliate=affiliate_user,
            email='old@test.com', phone='+15551234567',
        )
        Lead.objects.filter(pk=old.pk).update(updated_at=timezone.now() - timedelta(days=2))
        Lead.objects.create(
            intake_channel=Lead.CHANNEL_AFFILIATE_API, affiliate=affiliate_user,
            email='fresh@test.com', phone='+15551234567',
        )
        cutoff = (timezone.now() - timedelta(hours=1)).isoformat()
        client = _client_with_key(affiliate_api_key)
        resp = client.get(LIST_URL, {'updated_since': cutoff})
        emails = [l['email'] for l in resp.data['results']]
        assert 'fresh@test.com' in emails
        assert 'old@test.com' not in emails


@pytest.mark.django_db
class TestLeadDetail:
    def test_own_lead_returns_200(self, affiliate_api_key, affiliate_user):
        lead = Lead.objects.create(
            intake_channel=Lead.CHANNEL_AFFILIATE_API, affiliate=affiliate_user,
            email='mine@test.com', phone='+15551234567',
        )
        client = _client_with_key(affiliate_api_key)
        resp = client.get(f'{LIST_URL}/{lead.pk}')
        assert resp.status_code == 200
        assert resp.data['id'] == lead.pk

    def test_other_affiliates_lead_returns_404(self, affiliate_api_key):
        from django.contrib.auth import get_user_model
        from user_profile.models import Profile
        User = get_user_model()
        other = User.objects.create_user(username='other_affiliate2', password='pass')
        other.profile.role = Profile.Role.AFFILIATE
        other.profile.save(update_fields=['role'])

        lead = Lead.objects.create(
            intake_channel=Lead.CHANNEL_AFFILIATE_API, affiliate=other,
            email='not-mine@test.com', phone='+15551234567',
        )
        client = _client_with_key(affiliate_api_key)
        resp = client.get(f'{LIST_URL}/{lead.pk}')
        assert resp.status_code == 404

    def test_nonexistent_lead_returns_404(self, affiliate_api_key):
        client = _client_with_key(affiliate_api_key)
        resp = client.get(f'{LIST_URL}/999999')
        assert resp.status_code == 404

    def test_canonical_status_and_buyer_status_are_exposed(self, affiliate_api_key, affiliate_user):
        lead = Lead.objects.create(
            intake_channel=Lead.CHANNEL_AFFILIATE_API, affiliate=affiliate_user,
            email='status@test.com', phone='+15551234567',
            buyer_status='Asked for followup',
        )
        Lead.objects.filter(pk=lead.pk).update(canonical_status=canonical_status.CALLBACK)
        client = _client_with_key(affiliate_api_key)
        resp = client.get(f'{LIST_URL}/{lead.pk}')
        assert resp.data['canonical_status'] == canonical_status.CALLBACK
        assert resp.data['buyer_status'] == 'Asked for followup'


@pytest.mark.django_db
class TestStatusListEndpoint:
    def test_returns_full_canonical_vocabulary(self, affiliate_api_key):
        client = _client_with_key(affiliate_api_key)
        resp = client.get(STATUSES_URL)
        assert resp.status_code == 200
        values = {row['value'] for row in resp.data}
        assert values == canonical_status.VALUES

    def test_requires_affiliate_auth(self):
        client = APIClient()
        resp = client.get(STATUSES_URL)
        assert resp.status_code == 401
