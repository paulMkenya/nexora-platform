"""Admin Dashboard on the shared shell (templates/_shell/base_shell.html).

Phase 3 reference-page conversion: the operator/admin console moves from a
standalone top-nav (templates/admin_shared/nav.html) onto the same grouped,
collapsible sidebar shell the partner/advertiser side already uses, driven by
the nav registry (nexora/navigation.py). These tests pin: the sidebar renders
with every group from the registry, the old top-nav and its comment-leak bug
are gone, active state marks the current page, and platform-owner-only items
(Brands, Sales Funnel, Nexora Admin) are hidden from a non-owner operator.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase

from brands.models import Brand
from user_profile.models import Profile

User = get_user_model()


def _default_brand():
    return Brand.objects.create(
        slug='shell-admin', name='ShellAdminBrand',
        primary_domain='shell-admin.example.com', tracking_domain='t.shell-admin.example.com',
        is_default=True,
    )


class AdminDashboardShellTest(TestCase):
    def setUp(self):
        self.brand = _default_brand()

    def _sidebar(self, html):
        return html[html.find('id="nx-sidebar"'):html.find('<div class="nx-overlay"')]

    def test_platform_owner_sees_full_admin_nav(self):
        owner = User.objects.create_superuser(username='owner', email='owner@example.com', password='pass')
        self.client.force_login(owner)
        r = self.client.get('/admin/dashboard/')
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()

        self.assertIn('id="nx-sidebar"', html)
        self.assertNotIn('nx-anav', html)  # old top-nav gone
        self.assertNotIn('Owner/admin nav is restyled', html)  # comment-leak bug gone
        self.assertNotIn('href="#"', html)

        for group in ['Overview', 'People', 'Campaigns', 'Finance', 'Fraud', 'Growth', 'System']:
            self.assertIn(group, html)
        for item in ['Dashboard', 'Affiliates', 'Advertisers', 'Leads', 'Roles &amp; Admins',
                     'Offers', 'Brands', 'Payouts', 'Fraud Review', 'Sales Funnel', 'Email',
                     'API Docs', 'Nexora Admin', 'Archived', 'Impersonation']:
            self.assertIn(item, html)

        sidebar = self._sidebar(html)
        idx = sidebar.find('>Dashboard<')
        start = sidebar.rfind('<a class', 0, idx)
        self.assertIn('is-active', sidebar[start:idx])

    def test_non_owner_admin_hides_owner_only_items(self):
        admin_user = User.objects.create_user(username='netadmin', password='pass', is_staff=True)
        admin_user.profile.role = Profile.Role.NETWORK_ADMIN
        admin_user.profile.brand = self.brand
        admin_user.profile.save()
        self.client.force_login(admin_user)
        r = self.client.get('/admin/dashboard/')
        self.assertEqual(r.status_code, 200)
        sidebar = self._sidebar(r.content.decode())

        self.assertNotIn('Brands', sidebar)
        self.assertNotIn('Sales Funnel', sidebar)
        self.assertNotIn('Nexora Admin', sidebar)
        # Ungated items still present.
        self.assertIn('Email', sidebar)
        self.assertIn('Managers', sidebar)  # roles item relabeled for non-owners

    def test_affiliate_manager_sees_reduced_menu_only(self):
        manager = User.objects.create_user(username='mgr', password='pass', is_staff=True)
        manager.profile.role = Profile.Role.AFFILIATE_MANAGER
        manager.profile.brand = self.brand
        manager.profile.save()
        self.client.force_login(manager)
        r = self.client.get('/admin/dashboard/')
        self.assertEqual(r.status_code, 200)
        sidebar = self._sidebar(r.content.decode())

        self.assertIn('My Affiliates', sidebar)
        for absent in ['Dashboard', 'Payouts', 'Fraud Review', 'Brands', 'System']:
            self.assertNotIn(absent, sidebar)
