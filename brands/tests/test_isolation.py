"""
Two-brand fixture confirming complete data isolation.
Brand A cannot see Brand B's offers, advertisers, clicks, conversions.
"""
import pytest
from django.contrib.auth import get_user_model
from brands.models import Brand
from offer.models import Offer, Advertiser
from tracker.models import Click, Conversion

User = get_user_model()


@pytest.fixture
def brand_a(db):
    return Brand.objects.create(
        slug='brand-a', name='Brand A',
        primary_domain='a.example.com',
        tracking_domain='t.a.example.com',
        is_default=True,
    )


@pytest.fixture
def brand_b(db):
    return Brand.objects.create(
        slug='brand-b', name='Brand B',
        primary_domain='b.example.com',
        tracking_domain='t.b.example.com',
    )


@pytest.fixture
def adv_a(brand_a):
    return Advertiser.objects.create(company='Adv A', email='a@a.com', brand=brand_a)


@pytest.fixture
def adv_b(brand_b):
    return Advertiser.objects.create(company='Adv B', email='b@b.com', brand=brand_b)


@pytest.fixture
def offer_a(brand_a, adv_a):
    return Offer.objects.create(title='Offer A', brand=brand_a, advertiser=adv_a)


@pytest.fixture
def offer_b(brand_b, adv_b):
    return Offer.objects.create(title='Offer B', brand=brand_b, advertiser=adv_b)


@pytest.fixture
def user_a(brand_a):
    u = User.objects.create_user(username='affiliate_a', password='pass')
    profile = u.profile  # auto-created by post_save signal
    profile.brand = brand_a
    profile.save(update_fields=['brand'])
    return u


@pytest.fixture
def user_b(brand_b):
    u = User.objects.create_user(username='affiliate_b', password='pass')
    profile = u.profile
    profile.brand = brand_b
    profile.save(update_fields=['brand'])
    return u


@pytest.fixture
def click_a(brand_a, offer_a, user_a):
    return Click.objects.create(
        brand=brand_a, offer=offer_a, affiliate=user_a,
        ip='1.2.3.4', revenue='1.00', payout='0.50',
    )


@pytest.fixture
def click_b(brand_b, offer_b, user_b):
    return Click.objects.create(
        brand=brand_b, offer=offer_b, affiliate=user_b,
        ip='5.6.7.8', revenue='2.00', payout='1.00',
    )


@pytest.fixture
def conversion_a(brand_a, offer_a, user_a):
    return Conversion.objects.create(
        brand=brand_a, offer=offer_a, affiliate=user_a,
        ip='1.2.3.4', revenue='1.00', payout='0.50',
    )


@pytest.fixture
def conversion_b(brand_b, offer_b, user_b):
    return Conversion.objects.create(
        brand=brand_b, offer=offer_b, affiliate=user_b,
        ip='5.6.7.8', revenue='2.00', payout='1.00',
    )


class TestOfferIsolation:
    def test_brand_a_sees_only_own_offers(self, offer_a, offer_b, brand_a):
        qs = Offer.objects.for_brand(brand_a)
        assert offer_a in qs
        assert offer_b not in qs

    def test_brand_b_sees_only_own_offers(self, offer_a, offer_b, brand_b):
        qs = Offer.objects.for_brand(brand_b)
        assert offer_b in qs
        assert offer_a not in qs

    def test_unfiltered_sees_all(self, offer_a, offer_b):
        qs = Offer.objects.all()
        assert offer_a in qs
        assert offer_b in qs


class TestAdvertiserIsolation:
    def test_brand_a_sees_only_own_advertisers(self, adv_a, adv_b, brand_a):
        qs = Advertiser.objects.for_brand(brand_a)
        assert adv_a in qs
        assert adv_b not in qs

    def test_brand_b_sees_only_own_advertisers(self, adv_a, adv_b, brand_b):
        qs = Advertiser.objects.for_brand(brand_b)
        assert adv_b in qs
        assert adv_a not in qs


class TestClickIsolation:
    def test_brand_a_sees_only_own_clicks(self, click_a, click_b, brand_a):
        qs = Click.objects.for_brand(brand_a)
        assert click_a in qs
        assert click_b not in qs

    def test_brand_b_sees_only_own_clicks(self, click_a, click_b, brand_b):
        qs = Click.objects.for_brand(brand_b)
        assert click_b in qs
        assert click_a not in qs


class TestConversionIsolation:
    def test_brand_a_sees_only_own_conversions(self, conversion_a, conversion_b, brand_a):
        qs = Conversion.objects.for_brand(brand_a)
        assert conversion_a in qs
        assert conversion_b not in qs

    def test_brand_b_sees_only_own_conversions(self, conversion_a, conversion_b, brand_b):
        qs = Conversion.objects.for_brand(brand_b)
        assert conversion_b in qs
        assert conversion_a not in qs


class TestProfileIsolation:
    def test_brand_a_user_profile_has_correct_brand(self, user_a, brand_a):
        profile = user_a.profile
        assert profile.brand == brand_a

    def test_brand_b_user_profile_has_correct_brand(self, user_b, brand_b):
        profile = user_b.profile
        assert profile.brand == brand_b

    def test_brand_a_users_via_brand_relation(self, user_a, user_b, brand_a):
        brand_a_profiles = list(brand_a.users.all())
        assert user_a.profile in brand_a_profiles
        assert user_b.profile not in brand_a_profiles
