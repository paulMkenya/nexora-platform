from django.test import TestCase, override_settings

from user_profile.models import Profile, User


@override_settings(
    LOGIN_URL='/login/',
    LOGIN_REDIRECT_URL='/dashboard/',
)
class RolePortalMiddlewareTestCase(TestCase):
    def _make_user(self, username, password, role):
        user = User.objects.create_user(username=username, password=password)
        user.profile.role = role
        user.profile.save()
        return user

    # --- GET /login/ while already authenticated ---

    def test_affiliate_redirected_to_partner_on_login_get(self):
        user = self._make_user('aff', 'pass', Profile.Role.AFFILIATE)
        self.client.force_login(user)
        response = self.client.get('/login/')
        self.assertRedirects(response, '/partner/', fetch_redirect_response=False)

    def test_advertiser_redirected_to_advertiser_portal_on_login_get(self):
        user = self._make_user('adv', 'pass', Profile.Role.ADVERTISER)
        self.client.force_login(user)
        response = self.client.get('/login/')
        self.assertRedirects(response, '/advertiser/', fetch_redirect_response=False)

    def test_affiliate_manager_redirected_to_admin_on_login_get(self):
        user = self._make_user('mgr', 'pass', Profile.Role.AFFILIATE_MANAGER)
        self.client.force_login(user)
        response = self.client.get('/login/')
        self.assertRedirects(response, '/admin/', fetch_redirect_response=False)

    def test_network_admin_redirected_to_admin_on_login_get(self):
        user = self._make_user('nadm', 'pass', Profile.Role.NETWORK_ADMIN)
        self.client.force_login(user)
        response = self.client.get('/login/')
        self.assertRedirects(response, '/admin/', fetch_redirect_response=False)

    def test_unauthenticated_user_reaches_login_page(self):
        response = self.client.get('/login/')
        self.assertEqual(response.status_code, 200)

    # --- POST /login/ (successful login, no next param) ---

    def test_affiliate_post_login_redirected_to_partner(self):
        self._make_user('aff2', 'pass', Profile.Role.AFFILIATE)
        response = self.client.post('/login/', {'username': 'aff2', 'password': 'pass'})
        self.assertRedirects(response, '/partner/', fetch_redirect_response=False)

    def test_advertiser_post_login_redirected_to_advertiser(self):
        self._make_user('adv2', 'pass', Profile.Role.ADVERTISER)
        response = self.client.post('/login/', {'username': 'adv2', 'password': 'pass'})
        self.assertRedirects(response, '/advertiser/', fetch_redirect_response=False)

    def test_affiliate_manager_post_login_redirected_to_admin(self):
        self._make_user('mgr2', 'pass', Profile.Role.AFFILIATE_MANAGER)
        response = self.client.post('/login/', {'username': 'mgr2', 'password': 'pass'})
        self.assertRedirects(response, '/admin/', fetch_redirect_response=False)

    def test_network_admin_post_login_redirected_to_admin(self):
        self._make_user('nadm2', 'pass', Profile.Role.NETWORK_ADMIN)
        response = self.client.post('/login/', {'username': 'nadm2', 'password': 'pass'})
        self.assertRedirects(response, '/admin/', fetch_redirect_response=False)

    def test_post_login_with_next_param_not_overridden(self):
        """When ?next= is present the login view's own redirect is respected."""
        self._make_user('aff3', 'pass', Profile.Role.AFFILIATE)
        response = self.client.post(
            '/login/?next=/offers/',
            {'username': 'aff3', 'password': 'pass'},
        )
        # Should go to /offers/, not /partner/
        self.assertRedirects(response, '/offers/', fetch_redirect_response=False)
