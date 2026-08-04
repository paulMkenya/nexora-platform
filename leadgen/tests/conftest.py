import pytest
from django.contrib.auth import get_user_model

from brands.models import Brand
from offer.models import Advertiser, Offer
from public_api.models import APIKey
from user_profile.models import Profile

from leadgen.models import BoxType, LeadBuyer

User = get_user_model()


@pytest.fixture
def brand(db):
    return Brand.objects.update_or_create(
        slug='test-brand-leadgen',
        defaults=dict(name='Leadgen Test Brand', primary_domain='leadgen.test',
                      tracking_domain='t.leadgen.test', is_default=False),
    )[0]


@pytest.fixture
def affiliate_user(db, brand):
    user = User.objects.create_user(username='leadgen_affiliate', password='pass', email='aff@leadgen.test')
    user.profile.role = Profile.Role.AFFILIATE
    user.profile.brand = brand
    user.profile.save(update_fields=['role', 'brand'])
    return user


@pytest.fixture
def affiliate_api_key(db, affiliate_user):
    return APIKey.generate(user=affiliate_user, name='Affiliate Key', requests_per_hour=1000)


@pytest.fixture
def advertiser_user(db, brand):
    user = User.objects.create_user(username='leadgen_advertiser', password='pass', email='adv@leadgen.test')
    user.profile.role = Profile.Role.ADVERTISER
    user.profile.brand = brand
    user.profile.save(update_fields=['role', 'brand'])
    return user


@pytest.fixture
def advertiser_api_key(db, advertiser_user):
    """A key that authenticates fine but belongs to a non-affiliate account —
    used to prove IsAffiliate actually gates the inbound API."""
    return APIKey.generate(user=advertiser_user, name='Advertiser Key', requests_per_hour=1000)


@pytest.fixture
def advertiser(db, advertiser_user, brand):
    return Advertiser.objects.create(
        user=advertiser_user, brand=brand, company='LeadgenAdvCo', email='adv@leadgen.test',
    )


@pytest.fixture
def offer(db, brand, advertiser):
    return Offer.objects.create(
        title='Leadgen Test Offer', tracking_link='https://t.leadgen.test/click',
        brand=brand, advertiser=advertiser,
    )


@pytest.fixture
def box_type(db):
    """Phase 4's Box Registry template — matches the pre-Phase-4 `buyer`
    fixture's own values exactly, so every existing test's expectations
    (URLs, batch behavior, rate-limit shape) stay unchanged."""
    return BoxType.objects.create(
        name='Test Box', slug='test-box',
        connector_class='leadgen.connectors.LeadBuyerConnector',
        auth_type=BoxType.AUTH_API_KEY_QUERY,
        auth_param_name='apiKey',
        single_endpoint_path='/leads',
        batch_endpoint_path='/leads/batch',
        fetch_endpoint_path='/leads',
        batch_max_size=50,
        rate_limit_burst=10, rate_limit_refill_tokens=1, rate_limit_refill_seconds=1,
    )


@pytest.fixture
def buyer(db, brand, box_type):
    b = LeadBuyer.objects.create(
        brand=None, box_type=box_type,
        name='Test Buyer', slug='test-buyer',
        is_active=True, auto_inject=False,
        base_url='https://buyer.test/api',
        field_mapping={'firstname': 'FirstName', 'lastname': 'LastName',
                       'email': 'Email', 'phone': 'PhoneNumber'},
    )
    b.set_api_key('raw-test-secret')
    b.save(update_fields=['api_key_encrypted'])
    return b
