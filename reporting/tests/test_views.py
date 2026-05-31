"""Tests for /api/v1/reports/* endpoints."""
import pytest
from django.test import RequestFactory

from reporting.tests.conftest import refresh_matviews


@pytest.mark.django_db(transaction=True)
class TestReportEndpoints:
    def _auth_request(self, admin_user, url, params=None):
        from rest_framework.test import APIClient
        client = APIClient()
        client.force_authenticate(user=admin_user)
        return client, url, params or {}

    def _set_brand(self, request, brand):
        request.brand = brand

    def test_clicks_endpoint_returns_200(self, admin_user, brand_a, click_a):
        from rest_framework.test import APIClient
        refresh_matviews()

        client = APIClient()
        client.force_authenticate(user=admin_user)
        factory = RequestFactory()
        req = factory.get('/api/v1/reports/clicks')
        req.brand = brand_a
        req.user = admin_user

        from reporting.views import ClicksReportView
        view = ClicksReportView.as_view()
        resp = view(req)
        assert resp.status_code == 200
        assert 'results' in resp.data

    def test_conversions_endpoint_returns_200(self, admin_user, brand_a, conversion_a):
        refresh_matviews()

        factory = RequestFactory()
        req = factory.get('/api/v1/reports/conversions')
        req.brand = brand_a
        req.user = admin_user

        from reporting.views import ConversionsReportView
        view = ConversionsReportView.as_view()
        resp = view(req)
        assert resp.status_code == 200

    def test_revenue_endpoint_returns_200(self, admin_user, brand_a, click_a):
        refresh_matviews()

        factory = RequestFactory()
        req = factory.get('/api/v1/reports/revenue')
        req.brand = brand_a
        req.user = admin_user

        from reporting.views import RevenueReportView
        view = RevenueReportView.as_view()
        resp = view(req)
        assert resp.status_code == 200

    def test_etag_caching(self, admin_user, brand_a, click_a):
        """Second identical request with If-None-Match returns 304."""
        refresh_matviews()

        factory = RequestFactory()
        req = factory.get('/api/v1/reports/clicks')
        req.brand = brand_a
        req.user = admin_user

        from reporting.views import ClicksReportView
        view = ClicksReportView.as_view()
        resp1 = view(req)
        assert resp1.status_code == 200
        etag = resp1['ETag']

        req2 = factory.get('/api/v1/reports/clicks', HTTP_IF_NONE_MATCH=etag)
        req2.brand = brand_a
        req2.user = admin_user
        resp2 = view(req2)
        assert resp2.status_code == 304

    def test_brand_isolation_via_endpoints(self, admin_user, brand_a, brand_b, click_a, click_b):
        """Brand A endpoint does not return Brand B data."""
        refresh_matviews()

        factory = RequestFactory()

        from reporting.views import ClicksReportView
        view = ClicksReportView.as_view()

        req_a = factory.get('/api/v1/reports/clicks')
        req_a.brand = brand_a
        req_a.user = admin_user
        resp_a = view(req_a)

        req_b = factory.get('/api/v1/reports/clicks')
        req_b.brand = brand_b
        req_b.user = admin_user
        resp_b = view(req_b)

        # Both responses are successful
        assert resp_a.status_code == 200
        assert resp_b.status_code == 200
        # No data cross-contamination (check non-overlap of result sets)
        ids_a = {r.get('offer_id') for r in resp_a.data['results']}
        ids_b = {r.get('offer_id') for r in resp_b.data['results']}
        # If both have offer data, they should not overlap
        if ids_a and ids_b and None not in ids_a and None not in ids_b:
            assert ids_a.isdisjoint(ids_b)
