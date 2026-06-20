"""Shared app-shell sidebar (templates/_shell/sidebar.html).

One token-driven, role-aware sidebar is now used by both the affiliate and the
advertiser bases. These tests pin the reconciled behaviour: each role gets its
own menu, the current page is marked active, "coming soon" items are
non-clickable, and no other role's destinations leak in.
"""
from django.test import TestCase

from brands.models import Brand
from offer.models import Advertiser
from user_profile.models import Profile, User


def _default_brand():
    return Brand.objects.create(
        slug='shell', name='ShellBrand',
        primary_domain='shell.example.com', tracking_domain='t.shell.example.com',
        is_default=True,
    )


class AffiliateSidebarTest(TestCase):
    def setUp(self):
        self.brand = _default_brand()
        self.user = User.objects.create_user(username='aff', password='pass')
        p = self.user.profile
        p.role = Profile.Role.AFFILIATE
        p.affiliate_status = Profile.AffiliateStatus.APPROVED
        p.email_verified = True
        p.brand = self.brand
        p.save()
        self.client.force_login(self.user)

    def test_affiliate_menu_active_and_isolated(self):
        r = self.client.get('/partner/offers/')
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()

        # Shared shell partial rendered.
        self.assertIn('id="nx-sidebar"', html)
        # Affiliate menu items + group labels.
        for text in ['Dashboard', 'Offers', 'Payouts', 'Daily Report',
                     'Offer Report', 'Goal Report', 'Manage', 'Analyze', 'Tools']:
            self.assertIn(text, html)
        # Current page (offer_list) is marked active.
        idx = html.index('/partner/offers/')
        self.assertIn('is-active', html[max(0, idx - 200):idx + 50])
        # "Soon" items render disabled, and there are no dead links.
        self.assertIn('is-disabled', html)
        self.assertNotIn('href="#"', html)
        # No advertiser destinations leak into the affiliate shell.
        self.assertNotIn('/advertiser/', html)


class AdvertiserSidebarTest(TestCase):
    def setUp(self):
        self.brand = _default_brand()
        self.user = User.objects.create_user(username='adv', password='pass')
        self.user.profile.role = Profile.Role.ADVERTISER
        self.user.profile.save()
        # Sections are gated behind an approved advertiser record.
        Advertiser.objects.create(
            user=self.user, company='Shell Co', email='shell@example.com',
            advertiser_status=Advertiser.AdvertiserStatus.APPROVED, email_verified=True,
        )
        self.client.force_login(self.user)

    def test_advertiser_menu_active_and_isolated(self):
        r = self.client.get('/advertiser/offers/')
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()

        self.assertIn('id="nx-sidebar"', html)
        # Advertiser menu items + group labels + soon items.
        for text in ['Dashboard', 'Offers', 'Conversions', 'Postbacks',
                     'MMP Callbacks', 'Wallet', 'Settings',
                     'Overview', 'Performance', 'Billing', 'Account',
                     'Reports', 'Deposits']:
            self.assertIn(text, html)
        # Current page (offers) is marked active.
        idx = html.index('/advertiser/offers/')
        self.assertIn('is-active', html[max(0, idx - 200):idx + 50])
        # Soon items disabled, no dead links.
        self.assertIn('is-disabled', html)
        self.assertNotIn('href="#"', html)
        # No affiliate destinations leak into the advertiser shell.
        self.assertNotIn('/partner/', html)
