from django.test import TestCase
from django.urls import reverse

from user_profile.models import Profile, User


class AdvertiserAccessTestCase(TestCase):
    """Access-control tests for /advertiser/* — view layer lives in advertiser_ui."""

    def _make_user(self, username, role):
        user = User.objects.create_user(username=username, password='pass')
        user.profile.role = role
        user.profile.save()
        return user

    def test_unauthenticated_redirected_to_login(self):
        response = self.client.get('/advertiser/')
        self.assertRedirects(
            response,
            '/login/?next=/advertiser/',
            fetch_redirect_response=False,
        )

    def test_advertiser_can_access_dashboard(self):
        user = self._make_user('adv', Profile.Role.ADVERTISER)
        self.client.force_login(user)
        response = self.client.get('/advertiser/')
        self.assertEqual(response.status_code, 200)

    def test_affiliate_gets_403(self):
        user = self._make_user('aff', Profile.Role.AFFILIATE)
        self.client.force_login(user)
        self.assertEqual(self.client.get('/advertiser/').status_code, 403)

    def test_affiliate_manager_gets_403(self):
        user = self._make_user('mgr', Profile.Role.AFFILIATE_MANAGER)
        self.client.force_login(user)
        self.assertEqual(self.client.get('/advertiser/').status_code, 403)

    def test_network_admin_gets_403(self):
        user = self._make_user('nadm', Profile.Role.NETWORK_ADMIN)
        self.client.force_login(user)
        self.assertEqual(self.client.get('/advertiser/').status_code, 403)

    def test_dashboard_url_reverse(self):
        self.assertEqual(reverse('advertiser_ui:dashboard'), '/advertiser/')
