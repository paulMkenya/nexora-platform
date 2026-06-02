"""The Django model admin must be reachable only on platform-owner host(s).

On a brand/tenant domain the Django admin (and even its login) must never be
served — no Django branding leaks, and the platform-owner surface is invisible.
The custom operator console under /admin/ (other URL namespaces) must keep
working on brand domains.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from brands.models import Brand
from user_profile.models import Profile

User = get_user_model()

PLATFORM = 'platform.test'
BRAND = 'brand.test'


@override_settings(PLATFORM_ADMIN_HOSTS=[PLATFORM])
class AdminDomainLockdownTest(TestCase):
    def setUp(self):
        self.platform_brand = Brand.objects.create(
            slug='plat', name='Platform', primary_domain=PLATFORM,
            tracking_domain='t.platform.test', is_default=True)
        self.brand = Brand.objects.create(
            slug='brnd', name='WhiteLabel', primary_domain=BRAND,
            tracking_domain='t.brand.test')

        self.superuser = User.objects.create_superuser('root', 'root@x.com', 'pass')
        self.brand_admin = User.objects.create_user('ba', password='pass', is_staff=True)
        p = self.brand_admin.profile
        p.role = Profile.Role.NETWORK_ADMIN
        p.brand = self.brand
        p.save()

    # --- FIX 1: brand domain never exposes the Django admin ---

    def test_admin_login_on_brand_domain_redirects_to_operator_login(self):
        r = self.client.get('/admin/login/', HTTP_HOST=BRAND)
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r.url, '/partner/login/')

    def test_admin_index_on_brand_domain_redirects_even_for_superuser(self):
        self.client.force_login(self.superuser)
        r = self.client.get('/admin/', HTTP_HOST=BRAND)
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r.url, '/partner/login/')

    def test_no_django_branding_served_on_brand_domain(self):
        r = self.client.get('/admin/login/', HTTP_HOST=BRAND, follow=True)
        self.assertNotContains(r, 'Django administration')
        self.assertNotContains(r, 'Nexora Platform Admin')

    # --- FIX 1: platform host keeps working (superuser only) ---

    def test_admin_login_on_platform_host_renders(self):
        r = self.client.get('/admin/login/', HTTP_HOST=PLATFORM)
        self.assertEqual(r.status_code, 200)

    def test_admin_index_on_platform_host_superuser_ok(self):
        self.client.force_login(self.superuser)
        r = self.client.get('/admin/', HTTP_HOST=PLATFORM)
        self.assertEqual(r.status_code, 200)

    def test_brand_admin_bounced_from_admin_on_platform_host(self):
        self.client.force_login(self.brand_admin)
        r = self.client.get('/admin/', HTTP_HOST=PLATFORM)
        self.assertRedirects(r, '/admin/dashboard/', fetch_redirect_response=False)

    # --- FIX 2: rebranded chrome on the platform host ---

    def test_admin_login_is_rebranded(self):
        r = self.client.get('/admin/login/', HTTP_HOST=PLATFORM)
        self.assertContains(r, 'Nexora Platform Admin')
        self.assertNotContains(r, 'Django administration')

    # --- Regression: the custom console still works on brand domains ---

    def test_console_dashboard_works_on_brand_domain(self):
        self.client.force_login(self.brand_admin)
        self.assertEqual(self.client.get('/admin/dashboard/', HTTP_HOST=BRAND).status_code, 200)

    def test_console_affiliates_works_on_brand_domain(self):
        self.client.force_login(self.brand_admin)
        self.assertEqual(self.client.get('/admin/affiliates/', HTTP_HOST=BRAND).status_code, 200)

    def test_console_email_settings_works_on_brand_domain(self):
        self.client.force_login(self.brand_admin)
        self.assertEqual(self.client.get('/admin/brands/email-settings/', HTTP_HOST=BRAND).status_code, 200)

    def test_console_roles_works_on_brand_domain(self):
        self.client.force_login(self.brand_admin)
        self.assertEqual(self.client.get('/admin/roles/', HTTP_HOST=BRAND).status_code, 200)
