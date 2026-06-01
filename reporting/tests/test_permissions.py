"""
Authorization + scoping tests for /api/v1/reports/*.

The reporting endpoints expose brand-wide aggregates, so they must be locked to
network admins (brand-wide) and advertisers (own offers only). Affiliates and
other roles get 403, and an advertiser never sees another advertiser's — or
another brand's — data.
"""
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.test import RequestFactory

from offer.models import Advertiser, Offer
from reporting.tests.conftest import refresh_matviews
from reporting.views import ClicksReportView
from tracker.models import Click
from user_profile.models import Profile

User = get_user_model()


def _make_click(brand, offer, n=1, revenue='1.00', payout='0.50'):
    for _ in range(n):
        Click.objects.create(
            brand=brand, offer=offer, ip='1.2.3.4', country='US', ua='UA',
            revenue=Decimal(revenue), payout=Decimal(payout),
        )


def _get_clicks(user, brand, params=None):
    req = RequestFactory().get('/api/v1/reports/clicks', params or {})
    req.user = user
    req.brand = brand
    return ClicksReportView.as_view()(req)


def _total_clicks(resp):
    return sum(int(row.get('clicks') or 0) for row in resp.data['results'])


@pytest.fixture
def affiliate_user(db, brand_a):
    u = User.objects.create_user(username='aff_r', password='pass', email='aff_r@test.com')
    p = u.profile
    p.role = Profile.Role.AFFILIATE
    p.affiliate_status = Profile.AffiliateStatus.APPROVED
    p.email_verified = True
    p.brand = brand_a
    p.save()
    return u


@pytest.fixture
def network_admin_user(db, brand_a):
    u = User.objects.create_user(username='netadmin_r', password='pass', email='na_r@test.com')
    p = u.profile
    p.role = Profile.Role.NETWORK_ADMIN
    p.brand = brand_a
    p.save()
    return u


def _make_advertiser(username, brand):
    u = User.objects.create_user(username=username, password='pass', email=f'{username}@test.com')
    p = u.profile
    p.role = Profile.Role.ADVERTISER
    p.brand = brand
    p.save()
    adv = Advertiser.objects.create(user=u, company=f'{username} Co', email=f'{username}@test.com', brand=brand)
    return u, adv


@pytest.mark.django_db(transaction=True)
class TestReportingPermissions:
    def test_affiliate_gets_403(self, affiliate_user, brand_a, click_a):
        refresh_matviews()
        resp = _get_clicks(affiliate_user, brand_a)
        assert resp.status_code == 403

    def test_anonymous_gets_403(self, db, brand_a, click_a):
        from django.contrib.auth.models import AnonymousUser
        refresh_matviews()
        resp = _get_clicks(AnonymousUser(), brand_a)
        assert resp.status_code in (401, 403)

    def test_network_admin_sees_brand_aggregates(self, network_admin_user, brand_a, offer_a):
        # Two offers in brand A owned by nobody in particular — admin sees both.
        _make_click(brand_a, offer_a, n=3)
        refresh_matviews()
        resp = _get_clicks(network_admin_user, brand_a)
        assert resp.status_code == 200
        assert _total_clicks(resp) == 3

    def test_advertiser_sees_only_own_offers(self, db, brand_a):
        user1, adv1 = _make_advertiser('adv_one', brand_a)
        _, adv2 = _make_advertiser('adv_two', brand_a)
        offer1 = Offer.objects.create(title='Own', brand=brand_a, advertiser=adv1,
                                      tracking_link='https://a.test/c')
        offer2 = Offer.objects.create(title='Other', brand=brand_a, advertiser=adv2,
                                      tracking_link='https://a.test/c')
        _make_click(brand_a, offer1, n=2)
        _make_click(brand_a, offer2, n=5)
        refresh_matviews()

        resp = _get_clicks(user1, brand_a)
        assert resp.status_code == 200
        # Only adv1's 2 clicks, never adv2's 5.
        assert _total_clicks(resp) == 2

    def test_advertiser_with_no_offers_sees_nothing(self, db, brand_a, offer_a):
        user, _adv = _make_advertiser('adv_empty', brand_a)
        _make_click(brand_a, offer_a, n=4)  # belongs to no advertiser
        refresh_matviews()
        resp = _get_clicks(user, brand_a)
        assert resp.status_code == 200
        assert _total_clicks(resp) == 0

    def test_advertiser_cannot_read_other_brand(self, db, brand_a, brand_b):
        # Advertiser belongs to brand A; their offers/clicks are in brand A.
        user, adv = _make_advertiser('adv_xb', brand_a)
        offer = Offer.objects.create(title='A offer', brand=brand_a, advertiser=adv,
                                     tracking_link='https://a.test/c')
        _make_click(brand_a, offer, n=3)
        # Brand B has its own traffic on an offer the advertiser does not own.
        offer_b2 = Offer.objects.create(title='B offer', brand=brand_b,
                                        tracking_link='https://b.test/c')
        _make_click(brand_b, offer_b2, n=9)
        refresh_matviews()

        # Same user resolved onto brand B's domain must not see brand B data.
        resp = _get_clicks(user, brand_b)
        assert resp.status_code == 200
        assert _total_clicks(resp) == 0
