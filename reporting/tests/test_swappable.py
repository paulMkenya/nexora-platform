"""
Confirms the AggregationBackend abstraction is cleanly swappable.
Uses a MockBackend to verify views work with any backend implementation.
"""
from datetime import datetime, timezone
from unittest import mock

import pytest

from reporting.backends.base import AggregationBackend, ReportPage


class MockBackend(AggregationBackend):
    """Minimal in-memory backend for testing the abstraction contract."""

    CLICK_ROW = {'period': datetime(2024, 1, 1, tzinfo=timezone.utc), 'clicks': 42, 'revenue': 1.5, 'payout': 0.75}
    CONV_ROW = {'period': datetime(2024, 1, 1, tzinfo=timezone.utc), 'conversions_total': 10, 'conversions_approved': 8}
    REVENUE_ROW = {'period': datetime(2024, 1, 1, tzinfo=timezone.utc), 'clicks': 42, 'epc': 0.5, 'cr_pct': 2.4}

    def clicks_report(self, brand_id, date_from, date_to, group_by, filters, cursor, page_size):
        return ReportPage(results=[self.CLICK_ROW], next_cursor=None)

    def conversions_report(self, brand_id, date_from, date_to, group_by, filters, cursor, page_size):
        return ReportPage(results=[self.CONV_ROW], next_cursor=None)

    def revenue_report(self, brand_id, date_from, date_to, group_by, filters, cursor, page_size):
        return ReportPage(results=[self.REVENUE_ROW], next_cursor=None)


class TestBackendAbstraction:
    def test_mock_backend_satisfies_interface(self):
        """MockBackend must be accepted as an AggregationBackend."""
        backend = MockBackend()
        assert isinstance(backend, AggregationBackend)

    def test_get_backend_returns_postgres_by_default(self):
        from reporting.backends import get_backend
        from reporting.backends.postgres import PostgresMatViewBackend
        backend = get_backend()
        assert isinstance(backend, PostgresMatViewBackend)

    def test_get_backend_raises_on_unknown_name(self, settings):
        settings.REPORTING_BACKEND = 'unknown_db'
        from reporting.backends import get_backend
        with pytest.raises(ValueError, match='unknown_db'):
            get_backend()

    def test_views_use_injected_backend(self):
        """Report view calls get_backend() so swapping the backend swaps the data source."""
        from django.test import RequestFactory

        from brands.models import Brand

        factory = RequestFactory()
        req = factory.get('/api/v1/reports/clicks')
        req.user = mock.MagicMock(is_authenticated=True)
        req.brand = mock.MagicMock(spec=Brand)
        req.brand.pk = 99

        mock_backend = MockBackend()

        with mock.patch('reporting.views.get_backend', return_value=mock_backend):
            from reporting.views import ClicksReportView
            view = ClicksReportView.as_view()
            resp = view(req)

        assert resp.status_code == 200
        assert len(resp.data['results']) == 1
        assert resp.data['results'][0]['clicks'] == 42

    def test_report_page_dataclass(self):
        page = ReportPage(results=[{'clicks': 1}], next_cursor='abc')
        assert page.next_cursor == 'abc'
        assert page.results[0]['clicks'] == 1

    @pytest.mark.django_db
    def test_backend_is_replaced_by_settings(self, settings):
        """Setting REPORTING_BACKEND to a custom path raises (unknown); real swap is tested above."""
        settings.REPORTING_BACKEND = 'clickhouse'
        from reporting.backends import get_backend
        with pytest.raises(ValueError):
            get_backend()
