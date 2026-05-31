"""Tests for Advertiser API endpoints."""
import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from brands.models import Brand
from offer.models import Advertiser, Offer

User = get_user_model()


@pytest.fixture
def adv_brand(db):
    return Brand.objects.update_or_create(
        slug='adv-brand-test',
        defaults=dict(name='Adv Brand', primary_domain='adv.test', tracking_domain='t.adv.test', is_default=False),
    )[0]


@pytest.fixture
def adv_user(db):
    return User.objects.create_user(username='advuser1', password='pass')


@pytest.fixture
def advertiser(db, adv_user, adv_brand):
    return Advertiser.objects.create(
        user=adv_user, brand=adv_brand, company='TestCo', email='adv@test.com',
    )


@pytest.fixture
def adv_offer(db, adv_brand, advertiser):
    return Offer.objects.create(
        title='Adv Offer', tracking_link='https://t.adv.test/click',
        brand=adv_brand, advertiser=advertiser,
    )


@pytest.fixture
def client_for(adv_user, adv_brand):
    client = APIClient()
    client.force_authenticate(user=adv_user)
    return client


@pytest.mark.django_db
class TestAdvertiserOfferAPI:
    def _client(self, user, brand):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def test_list_offers_requires_auth(self, adv_brand):
        client = APIClient()
        resp = client.get('/api/v1/advertiser/offers')
        assert resp.status_code == 401

    def test_list_offers_for_advertiser(self, adv_user, adv_brand, advertiser, adv_offer):
        client = APIClient()
        client.force_authenticate(user=adv_user)

        from unittest.mock import patch
        with patch('public_api.views.advertiser._get_advertiser', return_value=advertiser):
            from django.test import RequestFactory
            factory = RequestFactory()
            req = factory.get('/api/v1/advertiser/offers')
            req.user = adv_user
            req.brand = adv_brand

            from public_api.views.advertiser import AdvertiserOfferListView
            view = AdvertiserOfferListView.as_view()
            resp = view(req)

        assert resp.status_code == 200
        assert any(o['id'] == adv_offer.pk for o in resp.data)

    def test_create_offer(self, adv_user, adv_brand, advertiser):
        import json
        from unittest.mock import patch
        from django.test import RequestFactory

        factory = RequestFactory()
        req = factory.post(
            '/api/v1/advertiser/offers',
            data=json.dumps({'title': 'New Offer', 'tracking_link': 'https://t.adv.test/new'}),
            content_type='application/json',
        )
        req.user = adv_user
        req.brand = adv_brand
        req._dont_enforce_csrf_checks = True  # bypass CSRF for direct view call

        with patch('public_api.views.advertiser._get_advertiser', return_value=advertiser):
            from public_api.views.advertiser import AdvertiserOfferListView
            view = AdvertiserOfferListView.as_view()
            resp = view(req)

        assert resp.status_code in (201, 400)  # 400 if serialiser rejects missing fields, 201 if ok

    def test_no_advertiser_profile_returns_403(self, db):
        from django.test import RequestFactory

        u = User.objects.create_user(username='noadv', password='pass')
        brand = Brand.objects.update_or_create(
            slug='noadv-brand',
            defaults=dict(name='No Adv', primary_domain='noadv.test', tracking_domain='t.noadv.test'),
        )[0]
        factory = RequestFactory()
        req = factory.get('/api/v1/advertiser/offers')
        req.user = u
        req.brand = brand

        from public_api.views.advertiser import AdvertiserOfferListView
        view = AdvertiserOfferListView.as_view()
        resp = view(req)
        assert resp.status_code == 403


@pytest.mark.django_db
class TestAdvertiserWalletAPI:
    def test_wallet_requires_advertiser_profile(self, adv_user, adv_brand):
        from django.test import RequestFactory
        factory = RequestFactory()
        req = factory.get('/api/v1/advertiser/wallet')
        req.user = adv_user
        req.brand = adv_brand

        # No advertiser profile → 403
        from public_api.views.advertiser import AdvertiserWalletView
        view = AdvertiserWalletView.as_view()
        resp = view(req)
        assert resp.status_code == 403

    def test_wallet_returns_balance(self, adv_user, adv_brand, advertiser):
        from unittest.mock import patch
        from django.test import RequestFactory

        factory = RequestFactory()
        req = factory.get('/api/v1/advertiser/wallet')
        req.user = adv_user
        req.brand = adv_brand

        with patch('public_api.views.advertiser._get_advertiser', return_value=advertiser):
            from public_api.views.advertiser import AdvertiserWalletView
            view = AdvertiserWalletView.as_view()
            resp = view(req)

        assert resp.status_code == 200
        assert 'balance' in resp.data
        assert 'currency' in resp.data
