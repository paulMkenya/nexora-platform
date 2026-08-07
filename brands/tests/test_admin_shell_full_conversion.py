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

    def test_brands_page_scoped_to_own_brand_after_shell_swap(self):
        """2026-08-07: the brands page is no longer owner-gated — a brand admin
        reaches it as its own brand's settings. What must survive the shell
        swap is the SCOPING, not a 403: it may never list another tenant. The
        cross-tenant create/delete actions are covered in test_admin_hierarchy."""
        other = Brand.objects.create(
            slug='other-tenant', name='Other Tenant',
            primary_domain='other.test', tracking_domain='t.other.test')
        non_owner = User.objects.create_user(username='netadmin2', password='pass', is_staff=True)
        non_owner.profile.role = Profile.Role.NETWORK_ADMIN
        non_owner.profile.brand = self.brand
        non_owner.profile.save()
        self.client.force_login(non_owner)
        r = self.client.get('/admin/brands/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual([b.pk for b in r.context['brands']], [self.brand.pk])
        self.assertNotContains(r, other.name)
