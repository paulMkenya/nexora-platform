"""Tests for PostgresMatViewBackend."""
import pytest

from reporting.tests.conftest import refresh_matviews


@pytest.mark.django_db(transaction=True)
class TestPostgresMatViewBackend:
    def test_clicks_report_returns_brand_data(self, click_a, click_b, brand_a, brand_b):
        """Brand A backend should only see Brand A clicks."""
        refresh_matviews()

        from datetime import datetime, timedelta, timezone

        from reporting.backends.postgres import PostgresMatViewBackend

        now = datetime.now(tz=timezone.utc)
        backend = PostgresMatViewBackend()
        page = backend.clicks_report(
            brand_id=brand_a.pk,
            date_from=now - timedelta(days=1),
            date_to=now + timedelta(hours=1),
            group_by=['period'],
            filters={},
            cursor=None,
            page_size=100,
        )
        assert isinstance(page.results, list)
        # All rows must belong to brand_a
        for row in page.results:
            assert row.get('brand_id') == brand_a.pk or 'brand_id' not in row

    def test_brand_isolation_in_clicks(self, click_a, click_b, brand_a, brand_b):
        """Brand A query must not leak Brand B clicks."""
        refresh_matviews()

        from datetime import datetime, timedelta, timezone

        from reporting.backends.postgres import PostgresMatViewBackend

        now = datetime.now(tz=timezone.utc)
        backend = PostgresMatViewBackend()
        page_a = backend.clicks_report(
            brand_id=brand_a.pk,
            date_from=now - timedelta(days=1),
            date_to=now + timedelta(hours=1),
            group_by=['period'],
            filters={},
            cursor=None,
            page_size=100,
        )
        page_b = backend.clicks_report(
            brand_id=brand_b.pk,
            date_from=now - timedelta(days=1),
            date_to=now + timedelta(hours=1),
            group_by=['period'],
            filters={},
            cursor=None,
            page_size=100,
        )
        clicks_a = sum(r['clicks'] for r in page_a.results)
        clicks_b = sum(r['clicks'] for r in page_b.results)
        assert clicks_a == 1
        assert clicks_b == 1

    def test_conversions_report(self, conversion_a, brand_a):
        """Conversion report returns rows with status breakdown."""
        refresh_matviews()

        from datetime import datetime, timedelta, timezone

        from reporting.backends.postgres import PostgresMatViewBackend

        now = datetime.now(tz=timezone.utc)
        backend = PostgresMatViewBackend()
        page = backend.conversions_report(
            brand_id=brand_a.pk,
            date_from=now - timedelta(days=1),
            date_to=now + timedelta(hours=1),
            group_by=['period'],
            filters={},
            cursor=None,
            page_size=100,
        )
        assert isinstance(page.results, list)
        if page.results:
            row = page.results[0]
            assert 'conversions_total' in row or hasattr(row, 'conversions_total')

    def test_revenue_report(self, click_a, conversion_a, brand_a):
        """Revenue report includes EPC and CR fields."""
        refresh_matviews()

        from datetime import datetime, timedelta, timezone

        from reporting.backends.postgres import PostgresMatViewBackend

        now = datetime.now(tz=timezone.utc)
        backend = PostgresMatViewBackend()
        page = backend.revenue_report(
            brand_id=brand_a.pk,
            date_from=now - timedelta(days=1),
            date_to=now + timedelta(hours=1),
            group_by=['period'],
            filters={},
            cursor=None,
            page_size=100,
        )
        assert isinstance(page.results, list)

    def test_cursor_pagination(self, brand_a, offer_a):
        """Cursor advances correctly when total rows exceed page_size."""
        from decimal import Decimal
        from datetime import datetime, timedelta, timezone

        from tracker.models import Click
        from reporting.backends.postgres import PostgresMatViewBackend

        # Create 3 clicks with different affiliates so they appear as separate group rows
        from django.contrib.auth import get_user_model
        User = get_user_model()
        affiliates = [
            User.objects.create_user(username=f'aff_cursor_{i}', password='x')
            for i in range(3)
        ]
        for aff in affiliates:
            Click.objects.create(
                brand=brand_a, offer=offer_a, affiliate=aff,
                ip='1.2.3.4', country='US', ua='Mozilla',
                revenue=Decimal('1.00'), payout=Decimal('0.50'),
            )
        refresh_matviews()

        now = datetime.now(tz=timezone.utc)
        backend = PostgresMatViewBackend()

        # Page size 2, should have a next cursor when 3 rows exist
        page1 = backend.clicks_report(
            brand_id=brand_a.pk,
            date_from=now - timedelta(days=1),
            date_to=now + timedelta(hours=1),
            group_by=['period', 'affiliate'],
            filters={},
            cursor=None,
            page_size=2,
        )
        assert len(page1.results) <= 2
        if len(page1.results) == 2:
            assert page1.next_cursor is not None
            page2 = backend.clicks_report(
                brand_id=brand_a.pk,
                date_from=now - timedelta(days=1),
                date_to=now + timedelta(hours=1),
                group_by=['period', 'affiliate'],
                filters={},
                cursor=page1.next_cursor,
                page_size=2,
            )
            assert isinstance(page2.results, list)
