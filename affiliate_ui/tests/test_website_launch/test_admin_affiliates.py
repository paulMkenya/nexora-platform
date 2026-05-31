"""Tests for network-admin affiliate management at /admin/affiliates/."""
from django.contrib.auth import get_user_model
from django.test import TestCase

from brands.models import Brand
from user_profile.models import Profile

User = get_user_model()


def _make_brand(slug='admin-test', domain='admin.example.com'):
    return Brand.objects.get_or_create(
        slug=slug,
        defaults=dict(
            name='AdminBrand',
            primary_domain=domain,
            tracking_domain=f't.{domain}',
            is_default=True,
        ),
    )[0]


def _make_user(username, role, brand=None):
    u = User.objects.create_user(username=username, password='pass')
    u.profile.role = role
    u.profile.brand = brand
    u.profile.save()
    return u


def _make_affiliate(username, brand=None, status=Profile.AffiliateStatus.PENDING):
    u = User.objects.create_user(username=username, password='pass')
    u.profile.role = Profile.Role.AFFILIATE
    u.profile.affiliate_status = status
    u.profile.brand = brand
    u.profile.save()
    return u


class AdminAffiliateListTest(TestCase):
    def setUp(self):
        self.brand_a = _make_brand('brand-a', 'brancha.example.com')
        # brand_b must NOT be default so BrandMiddleware falls back to brand_a
        self.brand_b = Brand.objects.create(
            slug='brand-b', name='BrandB',
            primary_domain='brandb.example.com',
            tracking_domain='t.brandb.example.com',
            is_default=False,
        )
        self.admin = _make_user('net_admin', Profile.Role.NETWORK_ADMIN, brand=self.brand_a)
        self.aff_a = _make_affiliate('aff_brand_a', brand=self.brand_a)
        self.aff_b = _make_affiliate('aff_brand_b', brand=self.brand_b)

    def test_list_requires_login(self):
        resp = self.client.get('/admin/affiliates/')
        self.assertEqual(resp.status_code, 302)

    def test_non_admin_gets_403(self):
        plain = _make_affiliate('plain_aff', brand=self.brand_a)
        self.client.force_login(plain)
        resp = self.client.get('/admin/affiliates/')
        self.assertEqual(resp.status_code, 403)

    def test_admin_sees_own_brand_affiliates(self):
        # brand_a is_default=True so BrandMiddleware returns it when no HTTP_HOST matches
        self.client.force_login(self.admin)
        resp = self.client.get('/admin/affiliates/')
        self.assertEqual(resp.status_code, 200)
        usernames = [p.user.username for p in resp.context['profiles']]
        self.assertIn('aff_brand_a', usernames)

    def test_admin_does_not_see_other_brand_affiliates(self):
        self.client.force_login(self.admin)
        resp = self.client.get('/admin/affiliates/')
        usernames = [p.user.username for p in resp.context['profiles']]
        self.assertNotIn('aff_brand_b', usernames)

    def test_status_filter(self):
        _make_affiliate('approved_aff', brand=self.brand_a, status=Profile.AffiliateStatus.APPROVED)
        self.client.force_login(self.admin)
        resp = self.client.get('/admin/affiliates/?status=APPROVED')
        usernames = [p.user.username for p in resp.context['profiles']]
        self.assertIn('approved_aff', usernames)
        self.assertNotIn('aff_brand_a', usernames)


class AdminAffiliateActionsTest(TestCase):
    def setUp(self):
        self.brand = _make_brand()
        self.admin = _make_user('action_admin', Profile.Role.NETWORK_ADMIN, brand=self.brand)
        self.aff = _make_affiliate('action_aff', brand=self.brand)

    def test_approve_sets_status_approved(self):
        self.client.force_login(self.admin)
        resp = self.client.post(f'/admin/affiliates/{self.aff.profile.pk}/approve/')
        self.assertRedirects(resp, '/admin/affiliates/', fetch_redirect_response=False)
        self.aff.profile.refresh_from_db()
        self.assertEqual(self.aff.profile.affiliate_status, Profile.AffiliateStatus.APPROVED)

    def test_reject_sets_status_rejected(self):
        self.client.force_login(self.admin)
        self.client.post(f'/admin/affiliates/{self.aff.profile.pk}/reject/')
        self.aff.profile.refresh_from_db()
        self.assertEqual(self.aff.profile.affiliate_status, Profile.AffiliateStatus.REJECTED)

    def test_suspend_sets_status_suspended(self):
        self.client.force_login(self.admin)
        self.client.post(f'/admin/affiliates/{self.aff.profile.pk}/suspend/')
        self.aff.profile.refresh_from_db()
        self.assertEqual(self.aff.profile.affiliate_status, Profile.AffiliateStatus.SUSPENDED)

    def test_approve_cross_brand_returns_404(self):
        # Create a second brand that is NOT the default so BrandMiddleware still returns self.brand
        other_brand = Brand.objects.create(
            slug='cross-brand', name='CrossBrand',
            primary_domain='cross.example.com',
            tracking_domain='t.cross.example.com',
            is_default=False,
        )
        other_aff = _make_affiliate('other_aff', brand=other_brand)
        self.client.force_login(self.admin)
        resp = self.client.post(f'/admin/affiliates/{other_aff.profile.pk}/approve/')
        self.assertEqual(resp.status_code, 404)
