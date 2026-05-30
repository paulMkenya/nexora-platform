from django.test import TestCase
from django.urls import reverse

from user_profile.models import Profile, User


class AdvertiserUiAccessMixin:
    def _make_user(self, username, role):
        user = User.objects.create_user(username=username, password='pass')
        user.profile.role = role
        user.profile.save()
        return user

    def _advertiser(self, suffix=''):
        return self._make_user(f'adv{suffix}', Profile.Role.ADVERTISER)

    def _non_advertiser(self, suffix=''):
        return self._make_user(f'aff{suffix}', Profile.Role.AFFILIATE)


class UrlReverseTestCase(TestCase):
    def test_url_reverses(self):
        self.assertEqual(reverse('advertiser_ui:dashboard'),    '/advertiser/')
        self.assertEqual(reverse('advertiser_ui:offers'),       '/advertiser/offers/')
        self.assertEqual(reverse('advertiser_ui:conversions'),  '/advertiser/conversions/')
        self.assertEqual(reverse('advertiser_ui:postbacks'),    '/advertiser/postbacks/')
        self.assertEqual(reverse('advertiser_ui:wallet'),       '/advertiser/wallet/')
        self.assertEqual(reverse('advertiser_ui:settings'),     '/advertiser/settings/')
        self.assertEqual(reverse('advertiser_ui:logout'),       '/advertiser/logout/')


class DashboardViewTestCase(AdvertiserUiAccessMixin, TestCase):
    url = '/advertiser/'

    def test_unauthenticated_redirected_to_login(self):
        r = self.client.get(self.url)
        self.assertRedirects(r, f'/login/?next={self.url}', fetch_redirect_response=False)

    def test_advertiser_gets_200(self):
        self.client.force_login(self._advertiser())
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 200)
        self.assertTemplateUsed(r, 'advertiser_ui/dashboard.html')
        self.assertTemplateUsed(r, 'advertiser_ui/base.html')

    def test_non_advertiser_gets_403(self):
        self.client.force_login(self._non_advertiser())
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_sidebar_links_present(self):
        self.client.force_login(self._advertiser('2'))
        r = self.client.get(self.url)
        for path in ['/advertiser/', '/advertiser/offers/', '/advertiser/conversions/',
                     '/advertiser/postbacks/', '/advertiser/wallet/', '/advertiser/settings/']:
            self.assertContains(r, path)

    def test_htmx_and_tailwind_cdn_loaded(self):
        self.client.force_login(self._advertiser('3'))
        r = self.client.get(self.url)
        self.assertContains(r, 'htmx.org')
        self.assertContains(r, 'cdn.tailwindcss.com')


class SectionViewsTestCase(AdvertiserUiAccessMixin, TestCase):
    sections = ['offers', 'conversions', 'postbacks', 'wallet', 'settings']

    def setUp(self):
        self.user = self._advertiser()
        self.client.force_login(self.user)

    def test_all_sections_return_200(self):
        for name in self.sections:
            with self.subTest(section=name):
                r = self.client.get(reverse(f'advertiser_ui:{name}'))
                self.assertEqual(r.status_code, 200)
                self.assertTemplateUsed(r, f'advertiser_ui/{name}.html')

    def test_all_sections_403_for_non_advertiser(self):
        non_adv = self._non_advertiser()
        self.client.force_login(non_adv)
        for name in self.sections:
            with self.subTest(section=name):
                self.assertEqual(
                    self.client.get(reverse(f'advertiser_ui:{name}')).status_code,
                    403,
                )


class LogoutViewTestCase(AdvertiserUiAccessMixin, TestCase):
    url = '/advertiser/logout/'

    def test_post_logs_out_and_redirects(self):
        self.client.force_login(self._advertiser())
        r = self.client.post(self.url)
        self.assertRedirects(r, '/login/', fetch_redirect_response=False)
        # Session should be cleared
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_active_sidebar_item_highlighted(self):
        self.client.force_login(self._advertiser('h'))
        # Offers page — offers link should be active
        r = self.client.get('/advertiser/offers/')
        content = r.content.decode()
        # Active item carries bg-gray-700 on the offers link
        offers_idx = content.index('/advertiser/offers/')
        self.assertIn('bg-gray-700', content[max(0, offers_idx - 200):offers_idx + 200])
