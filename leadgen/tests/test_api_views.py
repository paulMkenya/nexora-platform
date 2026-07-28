"""Tests for the inbound affiliate lead API (leadgen/api_views.py) — auth
(reused public_api.APIKey scheme), role gating, validation, and the batch
partial-success envelope."""
from unittest.mock import patch

import pytest
from rest_framework.test import APIClient

from leadgen.models import Lead

SUBMIT_URL = '/api/leads/submit'
BATCH_URL = '/api/leads/submit/batch'
LIST_URL = '/api/leads'


def _client_with_key(key):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f'ApiKey {key.secret}')
    return client


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

    def test_valid_affiliate_key_authenticates(self, affiliate_api_key):
        client = _client_with_key(affiliate_api_key)
        with patch('leadgen.api_views.maybe_auto_inject'):
            resp = client.post(SUBMIT_URL, {'email': 'a@test.com', 'phone': '+15551234567'}, format='json')
        assert resp.status_code == 201


@pytest.mark.django_db
class TestSubmitValidation:
    def test_missing_email_returns_400(self, affiliate_api_key):
        client = _client_with_key(affiliate_api_key)
        resp = client.post(SUBMIT_URL, {'phone': '+15551234567'}, format='json')
        assert resp.status_code == 400
        assert 'email' in resp.data

    def test_missing_phone_returns_400(self, affiliate_api_key):
        client = _client_with_key(affiliate_api_key)
        resp = client.post(SUBMIT_URL, {'email': 'a@test.com'}, format='json')
        assert resp.status_code == 400
        assert 'phone' in resp.data

    def test_invalid_phone_format_returns_400(self, affiliate_api_key):
        client = _client_with_key(affiliate_api_key)
        resp = client.post(SUBMIT_URL, {'email': 'a@test.com', 'phone': 'not-a-phone'}, format='json')
        assert resp.status_code == 400
        assert 'phone' in resp.data

    def test_valid_submission_creates_lead_with_correct_channel(self, affiliate_api_key, affiliate_user):
        client = _client_with_key(affiliate_api_key)
        with patch('leadgen.api_views.maybe_auto_inject'):
            resp = client.post(SUBMIT_URL, {
                'first_name': 'Jane', 'last_name': 'Doe',
                'email': 'jane@test.com', 'phone': '+15551234567', 'vertical': 'crypto',
            }, format='json')
        assert resp.status_code == 201
        lead = Lead.objects.get(email='jane@test.com')
        assert lead.intake_channel == Lead.CHANNEL_AFFILIATE_API
        assert lead.affiliate_id == affiliate_user.pk
        assert lead.vertical == 'crypto'
        assert lead.status == Lead.STATUS_NEW

    def test_submission_triggers_maybe_auto_inject(self, affiliate_api_key):
        client = _client_with_key(affiliate_api_key)
        with patch('leadgen.api_views.maybe_auto_inject') as mock_inject:
            client.post(SUBMIT_URL, {'email': 'a@test.com', 'phone': '+15551234567'}, format='json')
        mock_inject.assert_called_once()


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

    def test_over_max_batch_size_returns_400(self, affiliate_api_key):
        client = _client_with_key(affiliate_api_key)
        items = [{'email': f'x{i}@test.com', 'phone': '+15551234567'} for i in range(201)]
        resp = client.post(BATCH_URL, {'leads': items}, format='json')
        assert resp.status_code == 400

    def test_partial_success_envelope(self, affiliate_api_key):
        client = _client_with_key(affiliate_api_key)
        items = [
            {'email': 'good@test.com', 'phone': '+15551234567'},
            {'email': 'bad@test.com', 'phone': 'not-a-phone'},
        ]
        with patch('leadgen.api_views.maybe_auto_inject'):
            resp = client.post(BATCH_URL, {'leads': items}, format='json')
        assert resp.status_code == 201
        assert len(resp.data['addedLeads']) == 1
        assert len(resp.data['failedToAddLeads']) == 1
        assert resp.data['addedLeads'][0]['email'] == 'good@test.com'

    def test_all_failed_returns_400(self, affiliate_api_key):
        client = _client_with_key(affiliate_api_key)
        items = [{'email': 'bad@test.com', 'phone': 'not-a-phone'}]
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
        emails = [l['email'] for l in resp.data]
        assert 'mine@test.com' in emails
        assert 'not-mine@test.com' not in emails
