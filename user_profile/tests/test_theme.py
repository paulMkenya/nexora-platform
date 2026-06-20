from django.template.loader import get_template
from django.test import RequestFactory, TestCase
from django.urls import reverse

from user_profile.models import Profile, User


class ThemePreferenceDefaultTest(TestCase):
    def test_default_theme_is_dark(self):
        user = User.objects.create_user(username='aff', password='pass')
        self.assertEqual(user.profile.theme_preference, Profile.Theme.DARK)


class SetThemeEndpointTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='aff', password='pass')
        self.url = reverse('user_profile:set_theme')

    def test_post_requires_login(self):
        resp = self.client.post(self.url, {'theme': 'light'})
        self.assertEqual(resp.status_code, 302)  # redirect to LOGIN_URL

    def test_post_sets_light(self):
        self.client.force_login(self.user)
        resp = self.client.post(self.url, {'theme': 'light'})
        self.assertEqual(resp.status_code, 200)
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.theme_preference, Profile.Theme.LIGHT)

    def test_post_back_to_dark(self):
        self.user.profile.theme_preference = Profile.Theme.LIGHT
        self.user.profile.save()
        self.client.force_login(self.user)
        resp = self.client.post(self.url, {'theme': 'dark'})
        self.assertEqual(resp.status_code, 200)
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.theme_preference, Profile.Theme.DARK)

    def test_invalid_theme_rejected(self):
        self.client.force_login(self.user)
        resp = self.client.post(self.url, {'theme': 'rainbow'})
        self.assertEqual(resp.status_code, 400)
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.theme_preference, Profile.Theme.DARK)

    def test_get_not_allowed(self):
        self.client.force_login(self.user)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 405)


class BaseTemplatesRenderTest(TestCase):
    """Each role shell renders with the token system wired, no errors."""

    def setUp(self):
        self.rf = RequestFactory()

    def _request_for(self, role):
        user = User.objects.create_user(username=f'u_{role}', password='pass')
        user.profile.role = role
        user.profile.save()
        request = self.rf.get('/')
        request.user = user
        return request

    def test_affiliate_base_renders(self):
        request = self._request_for(Profile.Role.AFFILIATE)
        html = get_template('affiliate_ui/base.html').render({}, request)
        self.assertIn('data-theme', html)
        self.assertIn('nx-sidebar', html)
        self.assertIn('data-theme-toggle', html)

    def test_advertiser_base_renders(self):
        request = self._request_for(Profile.Role.ADVERTISER)
        html = get_template('advertiser_ui/base.html').render({}, request)
        self.assertIn('data-theme', html)
        self.assertIn('nx-sidebar', html)  # shared token-driven shell partial
        self.assertIn('data-theme-toggle', html)

    def test_owner_nav_renders(self):
        request = self._request_for(Profile.Role.NETWORK_ADMIN)
        html = get_template('admin_shared/nav.html').render({}, request)
        self.assertIn('nx-anav', html)
        self.assertIn('data-theme-toggle', html)
