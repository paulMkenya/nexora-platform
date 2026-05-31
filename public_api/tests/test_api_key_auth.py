"""Tests for API key authentication and OAuth2 token endpoint."""
import pytest
from django.test import RequestFactory
from rest_framework.exceptions import AuthenticationFailed

from public_api.authentication import APIKeyAuthentication


@pytest.mark.django_db
class TestAPIKeyAuthentication:
    def test_valid_key_authenticates(self, api_key, admin_user):
        auth = APIKeyAuthentication()
        factory = RequestFactory()
        req = factory.get('/', HTTP_AUTHORIZATION=f'ApiKey {api_key.secret}')
        user, credential = auth.authenticate(req)
        assert user == admin_user
        assert credential == api_key

    def test_invalid_key_raises(self, db):
        auth = APIKeyAuthentication()
        factory = RequestFactory()
        req = factory.get('/', HTTP_AUTHORIZATION='ApiKey notavalidkey')
        with pytest.raises(AuthenticationFailed):
            auth.authenticate(req)

    def test_wrong_scheme_returns_none(self, api_key):
        auth = APIKeyAuthentication()
        factory = RequestFactory()
        req = factory.get('/', HTTP_AUTHORIZATION=f'Bearer {api_key.secret}')
        result = auth.authenticate(req)
        assert result is None

    def test_missing_header_returns_none(self, db):
        auth = APIKeyAuthentication()
        factory = RequestFactory()
        req = factory.get('/')
        result = auth.authenticate(req)
        assert result is None

    def test_inactive_key_raises(self, api_key):
        api_key.is_active = False
        api_key.save(update_fields=['is_active'])
        auth = APIKeyAuthentication()
        factory = RequestFactory()
        req = factory.get('/', HTTP_AUTHORIZATION=f'ApiKey {api_key.secret}')
        with pytest.raises(AuthenticationFailed):
            auth.authenticate(req)

    def test_authenticate_sets_api_key_on_request(self, api_key, admin_user):
        auth = APIKeyAuthentication()
        factory = RequestFactory()
        req = factory.get('/', HTTP_AUTHORIZATION=f'ApiKey {api_key.secret}')
        auth.authenticate(req)
        assert req._api_key == api_key


@pytest.mark.django_db
class TestTokenEndpoint:
    def test_valid_credentials_return_token(self, api_key, admin_user):
        from rest_framework.test import APIClient
        client = APIClient()
        resp = client.post('/api/v1/auth/token', {
            'grant_type': 'client_credentials',
            'client_id': str(api_key.client_id),
            'client_secret': api_key.secret,
        }, format='json')
        assert resp.status_code == 200
        assert 'access_token' in resp.data
        assert resp.data['token_type'] == 'bearer'
        assert resp.data['expires_in'] == 3600

    def test_invalid_client_secret_returns_401(self, api_key):
        from rest_framework.test import APIClient
        client = APIClient()
        resp = client.post('/api/v1/auth/token', {
            'grant_type': 'client_credentials',
            'client_id': str(api_key.client_id),
            'client_secret': 'wrongsecret',
        }, format='json')
        assert resp.status_code == 401

    def test_missing_grant_type_returns_400(self, api_key):
        from rest_framework.test import APIClient
        client = APIClient()
        resp = client.post('/api/v1/auth/token', {
            'client_id': str(api_key.client_id),
            'client_secret': api_key.secret,
        }, format='json')
        assert resp.status_code == 400

    def test_api_key_list_requires_auth(self, db):
        from rest_framework.test import APIClient
        client = APIClient()
        resp = client.get('/api/v1/auth/keys')
        assert resp.status_code == 401

    def test_create_api_key(self, admin_user):
        from rest_framework.test import APIClient
        client = APIClient()
        client.force_authenticate(user=admin_user)
        resp = client.post('/api/v1/auth/keys', {'name': 'New Key'}, format='json')
        assert resp.status_code == 201
        assert 'secret' in resp.data
        assert resp.data['name'] == 'New Key'

    def test_deactivate_api_key(self, admin_user, api_key):
        from rest_framework.test import APIClient
        client = APIClient()
        client.force_authenticate(user=admin_user)
        resp = client.delete(f'/api/v1/auth/keys/{api_key.pk}')
        assert resp.status_code == 204
        api_key.refresh_from_db()
        assert not api_key.is_active
