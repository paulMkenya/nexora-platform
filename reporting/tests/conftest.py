from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model

from brands.models import Brand
from offer.models import Offer
from tracker.models import Click, Conversion

User = get_user_model()


def refresh_matviews(db_conn=None):
    """Refresh all reporting matviews; call after seeding data."""
    from django.db import connection
    views = [
        'reporting_click_hourly', 'reporting_click_daily',
        'reporting_conversion_hourly', 'reporting_conversion_daily',
    ]
    with connection.cursor() as cur:
        for v in views:
            cur.execute(f'REFRESH MATERIALIZED VIEW {v}')


@pytest.fixture
def brand_a(db):
    return Brand.objects.update_or_create(
        slug='brand-a',
        defaults=dict(name='Brand A', primary_domain='a.test', tracking_domain='t.a.test', is_default=False),
    )[0]


@pytest.fixture
def brand_b(db):
    return Brand.objects.update_or_create(
        slug='brand-b',
        defaults=dict(name='Brand B', primary_domain='b.test', tracking_domain='t.b.test', is_default=False),
    )[0]


@pytest.fixture
def admin_user(db):
    u = User.objects.create_superuser(username='admin_r', password='pass', email='admin_r@test.com')
    return u


@pytest.fixture
def offer_a(db, brand_a):
    return Offer.objects.create(
        title='Offer A', tracking_link='https://t.a.test/click', brand=brand_a,
    )


@pytest.fixture
def offer_b(db, brand_b):
    return Offer.objects.create(
        title='Offer B', tracking_link='https://t.b.test/click', brand=brand_b,
    )


@pytest.fixture
def click_a(db, brand_a, offer_a):
    return Click.objects.create(
        brand=brand_a, offer=offer_a,
        ip='1.2.3.4', country='US', ua='Mozilla/5.0',
        revenue=Decimal('1.00'), payout=Decimal('0.50'),
    )


@pytest.fixture
def click_b(db, brand_b, offer_b):
    return Click.objects.create(
        brand=brand_b, offer=offer_b,
        ip='5.6.7.8', country='GB', ua='Mozilla/5.0',
        revenue=Decimal('2.00'), payout=Decimal('1.00'),
    )


@pytest.fixture
def conversion_a(db, brand_a, offer_a):
    return Conversion.objects.create(
        brand=brand_a, offer=offer_a,
        ip='1.2.3.4', country='US', ua='Mozilla/5.0',
        revenue=Decimal('5.00'), payout=Decimal('3.00'),
        status='approved',
    )
