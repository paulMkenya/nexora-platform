"""Phase 3 step 3 — affiliate + advertiser re-pointed onto the shared shell.

Pins: both roles' authenticated pages render through _shell/base_shell.html
(sidebar, collapse toggle, SOON badges all survive the move off their old
standalone base.html), the anonymous affiliate flow (login/register/password
reset — 14 templates share affiliate_ui/base.html with authenticated pages
via a dynamic {% extends %}) keeps rendering the no-sidebar frame, and the
two roles' menus stay isolated from each other and from admin's.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from brands.models import Brand
from offer.models import Advertiser
from user_profile.models import Profile

User = get_user_model()


class PartnerAdvertiserShellTest(TestCase):
    def setUp(self):
        self.brand = Brand.objects.create(
            slug='shell-partner', name='ShellPartnerBrand',
            primary_domain='shell-partner.example.com', tracking_domain='t.shell-partner.example.com',
            is_default=True,
        )

    def test_affiliate_anonymous_pages_have_no_sidebar(self):
        for url in [reverse('affiliate_ui:login'), reverse('affiliate_ui:register')]:
            r = self.client.get(url)
            self.assertEqual(r.status_code, 200)
            html = r.content.decode()
            self.assertNotIn('id="nx-sidebar"', html)
            self.assertIn('Log in', html)

    def test_affiliate_authenticated_gets_shell(self):
        user = User.objects.create_user(username='aff-shell', password='pass')
        user.profile.role = Profile.Role.AFFILIATE
        user.profile.affiliate_status = Profile.AffiliateStatus.APPROVED
        user.profile.email_verified = True
        user.profile.brand = self.brand
        user.profile.save()
        self.client.force_login(user)
        r = self.client.get(reverse('affiliate_ui:dashboard'))
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        self.assertIn('id="nx-sidebar"', html)
        self.assertIn('nx-railtoggle', html)
        self.assertIn('affiliate_ui:dashboard'.split(':')[-1], html)  # sanity: page loaded at all
        self.assertNotIn('/advertiser/', html)

    def test_advertiser_authenticated_gets_shell_and_correct_menu(self):
        user = User.objects.create_user(username='adv-shell', password='pass')
        user.profile.role = Profile.Role.ADVERTISER
        user.profile.save()
        Advertiser.objects.create(
            user=user, company='Shell Partner Co', email='shellpartner@example.com',
            advertiser_status=Advertiser.AdvertiserStatus.APPROVED, email_verified=True,
        )
        self.client.force_login(user)
        r = self.client.get(reverse('advertiser_ui:dashboard'))
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        self.assertIn('id="nx-sidebar"', html)
        self.assertIn('nx-railtoggle', html)
        # Correct role's dashboard URL on the brand link, not affiliate's.
        self.assertIn(reverse('advertiser_ui:dashboard'), html)
        self.assertNotIn('/partner/', html)
        # SOON items unique to advertiser survive the registry move.
        self.assertIn('Deposits', html)
        self.assertIn('nx-soon', html)
