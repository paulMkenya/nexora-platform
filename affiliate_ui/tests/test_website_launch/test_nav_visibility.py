"""Bug 1 regression: anonymous visitors must not see the gated affiliate nav."""
from django.contrib.auth import get_user_model
from django.test import TestCase

from brands.models import Brand
from user_profile.models import Profile

User = get_user_model()


def _make_brand():
    return Brand.objects.create(
        slug='navtest', name='NavBrand',
        primary_domain='nav.example.com', tracking_domain='t.nav.example.com',
        is_default=True,
    )


class AnonymousNavTest(TestCase):
    def setUp(self):
        self.brand = _make_brand()

    def test_register_page_hides_app_nav_for_anonymous(self):
        resp = self.client.get('/partner/register/')
        self.assertEqual(resp.status_code, 200)
        # Gated app links must be absent for anonymous visitors.
        self.assertNotContains(resp, 'href="/partner/offers/"')
        self.assertNotContains(resp, 'href="/partner/payouts/"')
        # Minimal header offers Log in / Register instead.
        self.assertContains(resp, 'Log in')
        self.assertContains(resp, 'Register')

    def test_login_page_hides_app_nav_for_anonymous(self):
        resp = self.client.get('/partner/login/')
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'href="/partner/offers/"')


class AuthenticatedNavTest(TestCase):
    def setUp(self):
        self.brand = _make_brand()
        self.user = User.objects.create_user(
            username='aff@example.com', email='aff@example.com', password='pass')
        p = self.user.profile
        p.role = Profile.Role.AFFILIATE
        p.affiliate_status = Profile.AffiliateStatus.APPROVED
        p.email_verified = True
        p.brand = self.brand
        p.save()
        self.client.force_login(self.user)

    def test_dashboard_shows_app_nav_for_authenticated(self):
        resp = self.client.get('/partner/dashboard/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'href="/partner/offers/"')
        self.assertContains(resp, 'href="/partner/payouts/"')
        self.assertContains(resp, 'Log out')
