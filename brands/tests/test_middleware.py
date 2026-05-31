import pytest
from django.test import RequestFactory
from brands.middleware import BrandMiddleware
from brands.models import Brand


def _make_response(_request):
    from django.http import HttpResponse
    return HttpResponse()


@pytest.fixture
def nexora_brand(db):
    # Use get_or_create to handle the data migration brand row
    brand, _ = Brand.objects.update_or_create(
        slug='nexora',
        defaults={
            'name': 'Nexora',
            'primary_domain': 'cpa.test.local',
            'tracking_domain': 't.test.local',
            'is_default': True,
        },
    )
    return brand


@pytest.fixture
def acme_brand(db):
    return Brand.objects.create(
        slug='acme', name='Acme',
        primary_domain='app.acme.local',
        tracking_domain='t.acme.local',
    )


class TestBrandMiddleware:
    def _get_middleware(self):
        return BrandMiddleware(_make_response)

    def test_resolves_primary_domain(self, nexora_brand, acme_brand):
        rf = RequestFactory()
        request = rf.get('/', HTTP_HOST='app.acme.local')
        self._get_middleware()(request)
        assert request.brand == acme_brand

    def test_resolves_tracking_domain(self, nexora_brand, acme_brand):
        rf = RequestFactory()
        request = rf.get('/', HTTP_HOST='t.acme.local')
        self._get_middleware()(request)
        assert request.brand == acme_brand

    def test_unknown_host_falls_back_to_default(self, nexora_brand, acme_brand):
        rf = RequestFactory()
        request = rf.get('/', HTTP_HOST='unknown.example.com')
        self._get_middleware()(request)
        assert request.brand == nexora_brand

    def test_resolves_nexora_primary_domain(self, nexora_brand):
        rf = RequestFactory()
        request = rf.get('/', HTTP_HOST='cpa.test.local')
        self._get_middleware()(request)
        assert request.brand == nexora_brand

    def test_host_port_stripped(self, nexora_brand, acme_brand):
        rf = RequestFactory()
        request = rf.get('/', HTTP_HOST='app.acme.local:8000')
        self._get_middleware()(request)
        assert request.brand == acme_brand
