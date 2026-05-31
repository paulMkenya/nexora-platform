import pytest
from django.contrib.auth import get_user_model

from brands.models import Brand
from public_api.models import APIKey, WebhookEndpoint

User = get_user_model()


@pytest.fixture
def brand(db):
    return Brand.objects.update_or_create(
        slug='test-brand-api',
        defaults=dict(name='API Test Brand', primary_domain='api.test', tracking_domain='t.api.test', is_default=False),
    )[0]


@pytest.fixture
def admin_user(db):
    u = User.objects.create_superuser(username='apiadmin', password='pass', email='apiadmin@test.com')
    return u


@pytest.fixture
def regular_user(db):
    u = User.objects.create_user(username='apiuser', password='pass', email='apiuser@test.com')
    return u


@pytest.fixture
def api_key(db, admin_user):
    return APIKey.generate(user=admin_user, name='Test Key', requests_per_hour=10)


@pytest.fixture
def webhook_endpoint(db, brand):
    import secrets
    return WebhookEndpoint.objects.create(
        brand=brand,
        url='https://webhook.test/receive',
        secret=secrets.token_urlsafe(32),
        events=['offer.created', 'conversion.approved'],
        is_active=True,
    )
