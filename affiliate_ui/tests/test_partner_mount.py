"""
Tests confirming affiliate_ui is correctly mounted at /partner/.

Key assertions:
  - /partner/         → 302 for anonymous (redirect chain ends at login)
  - /partner/         → 200 (follow=True) for an authenticated affiliate
  - /partner/dashboard/ → 302→/partner/login/ for anonymous
  - /partner/login/   → 200 (login form) for everyone
  - /login/           → 200 (standalone route, backward compat)
  - reverse('affiliate_ui:dashboard') resolves to /partner/dashboard/
"""
from django.test import TestCase
from django.urls import reverse

from user_profile.models import Profile


def _make_affiliate(username='partner_test_aff'):
    from django.contrib.auth import get_user_model
    User = get_user_model()
    u = User.objects.create_user(username=username, password='pass')
    u.profile.role = Profile.Role.AFFILIATE
    u.profile.save()
    return u


class PartnerMountTest(TestCase):

    def test_partner_root_anonymous_redirects(self):
        """Unauthenticated GET /partner/ → first response is 302."""
        resp = self.client.get('/partner/')
        self.assertEqual(resp.status_code, 302)

    def test_partner_root_anonymous_chain_reaches_login(self):
        """Following the full chain from /partner/ lands on the login page."""
        resp = self.client.get('/partner/', follow=True)
        self.assertEqual(resp.status_code, 200)
        final_url, _ = resp.redirect_chain[-1]
        self.assertIn('/partner/login/', final_url)

    def test_partner_root_affiliate_follows_to_200(self):
        """/partner/ for a logged-in affiliate follows to dashboard (200)."""
        user = _make_affiliate('partner_aff_200')
        self.client.force_login(user)
        resp = self.client.get('/partner/', follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, 'affiliate_ui/dashboard.html')

    def test_partner_dashboard_anonymous_302_to_login(self):
        """Anonymous /partner/dashboard/ → 302 redirecting to login."""
        resp = self.client.get('/partner/dashboard/')
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/partner/login/', resp['Location'])

    def test_partner_dashboard_affiliate_200(self):
        """/partner/dashboard/ for an authenticated affiliate → 200."""
        user = _make_affiliate('partner_aff_dash')
        self.client.force_login(user)
        resp = self.client.get('/partner/dashboard/')
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, 'affiliate_ui/dashboard.html')

    def test_partner_login_page_200_anonymous(self):
        """/partner/login/ renders the login form for unauthenticated users."""
        resp = self.client.get('/partner/login/')
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, 'affiliate_ui/login.html')

    def test_legacy_login_route_still_200(self):
        """/login/ standalone route continues to serve the login form."""
        resp = self.client.get('/login/')
        self.assertEqual(resp.status_code, 200)

    def test_reverse_resolves_to_partner_prefix(self):
        """Named URLs resolve under /partner/."""
        self.assertEqual(reverse('affiliate_ui:dashboard'), '/partner/dashboard/')
        self.assertEqual(reverse('affiliate_ui:login'), '/partner/login/')
        self.assertEqual(reverse('affiliate_ui:offer_list'), '/partner/offers/')

    def test_partner_offers_affiliate_200(self):
        user = _make_affiliate('partner_aff_offers')
        self.client.force_login(user)
        resp = self.client.get('/partner/offers/')
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, 'affiliate_ui/offers.html')

    def test_partner_reports_affiliate_200(self):
        user = _make_affiliate('partner_aff_reports')
        self.client.force_login(user)
        resp = self.client.get('/partner/reports/daily/')
        self.assertEqual(resp.status_code, 200)


class PartnerLoginFlowTest(TestCase):
    """Login POST → middleware routes affiliate to /partner/."""

    def setUp(self):
        self.user = _make_affiliate('partner_login_flow')

    def test_login_post_redirects_to_partner(self):
        resp = self.client.post(
            '/partner/login/',
            {'username': 'partner_login_flow', 'password': 'pass'},
        )
        self.assertRedirects(resp, '/partner/', fetch_redirect_response=False)

    def test_already_logged_in_at_partner_login_redirects_to_partner(self):
        self.client.force_login(self.user)
        resp = self.client.get('/partner/login/')
        self.assertRedirects(resp, '/partner/', fetch_redirect_response=False)
