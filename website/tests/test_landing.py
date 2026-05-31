"""Tests for the landing page and role-based root redirect."""
from django.test import TestCase
from django.contrib.auth import get_user_model

from user_profile.models import Profile

User = get_user_model()


def _make_user(username, role, *, approved=True):
    u = User.objects.create_user(username=username, password='pass')
    u.profile.role = role
    if approved and role == Profile.Role.AFFILIATE:
        u.profile.affiliate_status = Profile.AffiliateStatus.APPROVED
        u.profile.email_verified = True
    u.profile.save()
    return u


class LandingPageTest(TestCase):
    def test_anonymous_root_returns_landing(self):
        resp = self.client.get('/')
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, 'website/landing.html')

    def test_authenticated_affiliate_root_redirects_to_partner(self):
        user = _make_user('aff_root', Profile.Role.AFFILIATE)
        self.client.force_login(user)
        resp = self.client.get('/')
        self.assertRedirects(resp, '/partner/', fetch_redirect_response=False)

    def test_authenticated_advertiser_root_redirects_to_advertiser(self):
        user = _make_user('adv_root', Profile.Role.ADVERTISER)
        self.client.force_login(user)
        resp = self.client.get('/')
        self.assertRedirects(resp, '/advertiser/', fetch_redirect_response=False)

    def test_authenticated_admin_root_redirects_to_admin(self):
        user = _make_user('adm_root', Profile.Role.NETWORK_ADMIN)
        self.client.force_login(user)
        resp = self.client.get('/')
        self.assertRedirects(resp, '/admin/', fetch_redirect_response=False)

    def test_authenticated_manager_root_redirects_to_admin(self):
        user = _make_user('mgr_root', Profile.Role.AFFILIATE_MANAGER)
        self.client.force_login(user)
        resp = self.client.get('/')
        self.assertRedirects(resp, '/admin/', fetch_redirect_response=False)

    def test_landing_contains_register_cta(self):
        resp = self.client.get('/')
        self.assertContains(resp, '/partner/register/')

    def test_landing_contains_login_cta(self):
        resp = self.client.get('/')
        self.assertContains(resp, '/partner/login/')
