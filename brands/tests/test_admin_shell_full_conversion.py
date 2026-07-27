"""Phase 3 step 2 — every remaining admin page converted onto the shared shell.

Pins the full sweep: each admin URL renders through the shell (sidebar
present, old top-nav gone) for a platform owner, and the owner-only Brands
page still correctly gates a non-owner operator — the shell swap didn't
touch access control.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase

from brands.models import Brand
from user_profile.models import Profile

User = get_user_model()

ADMIN_GET_URLS = [
    '/admin/dashboard/',
    '/admin/affiliates/',
    '/admin/advertisers/',
    '/admin/leads/',
    '/admin/roles/',
    '/admin/offers/',
    '/admin/offers/new/',
    '/admin/brands/',
    '/admin/brands/new/',
    '/admin/brands/email-settings/',
    '/admin/payouts/',
    '/admin/payouts/batches/',
    '/admin/payouts/holds/',
    '/admin/payouts/controls/',
    '/admin/fraud/',
    '/admin/platform-leads/',
    '/admin/platform-leads/settings/',
    '/admin/archived/',
    '/admin/impersonate/log/',
]


class AdminShellFullConversionTest(TestCase):
    def setUp(self):
        self.brand = Brand.objects.create(
            slug='shell-full', name='ShellFullBrand',
            primary_domain='shell-full.example.com', tracking_domain='t.shell-full.example.com',
            is_default=True,
        )
        self.owner = User.objects.create_superuser(
            username='owner2', email='owner2@example.com', password='pass')

    def test_every_admin_page_renders_through_shell(self):
        self.client.force_login(self.owner)
        for url in ADMIN_GET_URLS:
            with self.subTest(url=url):
                r = self.client.get(url)
                self.assertEqual(r.status_code, 200, f'{url} did not return 200')
                html = r.content.decode()
                self.assertIn('id="nx-sidebar"', html, f'{url} missing shared sidebar')
                self.assertNotIn('nx-anav', html, f'{url} still renders the old top-nav')

    def test_brands_page_still_owner_gated_after_shell_swap(self):
        non_owner = User.objects.create_user(username='netadmin2', password='pass', is_staff=True)
        non_owner.profile.role = Profile.Role.NETWORK_ADMIN
        non_owner.profile.brand = self.brand
        non_owner.profile.save()
        self.client.force_login(non_owner)
        r = self.client.get('/admin/brands/')
        self.assertNotEqual(r.status_code, 200)
