"""Shared sign-in pages: one white-label layout for partner, advertiser, team
and platform-admin logins."""
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from brands.models import Brand
from brands.templatetags.brand_colors import on_color, safe_hex

User = get_user_model()
HOST = 'app.signin-brand.example'


@override_settings(ALLOWED_HOSTS=['*'])
class SignInPagesTest(TestCase):

    def setUp(self):
        self.brand = Brand.objects.create(
            name='ChainPulse', slug='signin-cp', primary_domain=HOST,
            tracking_domain='track.signin-brand.example', primary_color='#f7931a',
            secondary_color='#0b0e17', support_email='help@signin-brand.example')

    def _get(self, url):
        return self.client.get(url, HTTP_HOST=HOST)

    def test_partner_page_is_branded_with_tabs_and_signup(self):
        r = self._get('/partner/login/')
        self.assertTemplateUsed(r, 'auth/layout.html')
        self.assertContains(r, 'Partner portal')
        self.assertContains(r, '--brand: #f7931a')
        self.assertContains(r, '--on-brand: #0b0e17')  # dark text on orange
        self.assertContains(r, 'Apply to join')
        self.assertContains(r, 'aria-current="page">Partner<')
        self.assertContains(r, 'autocomplete="current-password"')

    def test_team_view_has_operator_copy_and_no_signup(self):
        r = self._get('/partner/login/?portal=team')
        self.assertContains(r, 'Network operations')
        self.assertContains(r, 'aria-current="page">Team<')
        self.assertNotContains(r, 'Apply to join')

    def test_advertiser_page(self):
        r = self._get('/advertiser/login/')
        self.assertContains(r, 'Advertiser console')
        self.assertContains(r, 'Create an advertiser account')

    def test_brand_admin_login_lands_on_team_view(self):
        r = self._get('/admin/login/')
        self.assertEqual(r.url, '/partner/login/?portal=team')

    def test_wrong_password_shows_friendly_error_and_keeps_username(self):
        r = self.client.post('/partner/login/', {'username': 'who@example.com', 'password': 'x'}, HTTP_HOST=HOST)
        self.assertContains(r, "don't match")
        self.assertContains(r, 'value="who@example.com"')

    def test_team_sign_in_still_routes_operators_to_their_console(self):
        user = User.objects.create_user(username='op', password='pw-123456')
        user.profile.role = 'NETWORK_ADMIN'
        user.profile.save()
        r = self.client.post('/partner/login/?portal=team', {'username': 'op', 'password': 'pw-123456'}, HTTP_HOST=HOST)
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r.url, '/admin/dashboard/')

    def test_bad_brand_colour_cannot_inject_css(self):
        Brand.objects.filter(pk=self.brand.pk).update(primary_color='red;}x{')
        r = self._get('/partner/login/')
        self.assertNotContains(r, 'red;}x{')
        self.assertContains(r, '--brand: #6366f1')


class BrandColourFilterTest(TestCase):

    def test_on_color_picks_the_readable_text_colour(self):
        self.assertEqual(on_color('#f7931a'), '#0b0e17')
        self.assertEqual(on_color('#4f46e5'), '#ffffff')
        self.assertEqual(on_color('nonsense'), '#ffffff')

    def test_safe_hex(self):
        self.assertEqual(safe_hex('#ABCDEF'), '#ABCDEF')
        self.assertEqual(safe_hex('url(x)'), '#6366f1')
