"""Tests for the leads-injection section embedded directly on
/admin/dashboard/ (brands/views/admin_views.py: dashboard + inject_
consumer_leads) — brand scoping for non-superuser operators, and staff
gating on the inject action."""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from brands.models import Brand
from leadgen.models import Lead, LeadBuyer, LeadInjection
from user_profile.models import Profile

User = get_user_model()


def _brand(slug):
    return Brand.objects.create(
        slug=slug, name=slug, primary_domain=f'{slug}.example.com',
        tracking_domain=f't.{slug}.example.com',
    )


class AdminDashboardLeadsSectionTest(TestCase):
    def setUp(self):
        self.brand_a = _brand('dash-leads-a')
        self.brand_b = _brand('dash-leads-b')
        self.buyer_a = LeadBuyer.objects.create(
            brand=self.brand_a, name='Buyer A', slug='dash-buyer-a',
            is_active=True, base_url='https://buyer-a.test',
        )
        self.buyer_b = LeadBuyer.objects.create(
            brand=self.brand_b, name='Buyer B', slug='dash-buyer-b',
            is_active=True, base_url='https://buyer-b.test',
        )
        self.lead_a = Lead.objects.create(
            intake_channel=Lead.CHANNEL_LANDING_PAGE, brand=self.brand_a,
            email='lead-a@test.com', phone='+15551110000',
        )
        self.lead_b = Lead.objects.create(
            intake_channel=Lead.CHANNEL_LANDING_PAGE, brand=self.brand_b,
            email='lead-b@test.com', phone='+15552220000',
        )

    def _operator(self, brand):
        user = User.objects.create_user(username=f'op_{brand.slug}', password='pass', is_staff=True)
        user.profile.role = Profile.Role.NETWORK_ADMIN
        user.profile.brand = brand
        user.profile.save()
        return user

    def test_dashboard_shows_only_own_brand_leads(self):
        user = self._operator(self.brand_a)
        self.client.force_login(user)
        r = self.client.get('/admin/dashboard/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'lead-a@test.com')
        self.assertNotContains(r, 'lead-b@test.com')

    def test_superuser_sees_all_brands_leads(self):
        owner = User.objects.create_superuser(username='dash_owner', email='o@test.com', password='pass')
        self.client.force_login(owner)
        r = self.client.get('/admin/dashboard/')
        self.assertContains(r, 'lead-a@test.com')
        self.assertContains(r, 'lead-b@test.com')

    def test_inject_anonymous_redirect(self):
        r = self.client.post('/admin/dashboard/inject-leads/', {
            'buyer_id': str(self.buyer_a.pk), 'lead_ids': [str(self.lead_a.pk)],
        })
        self.assertEqual(r.status_code, 302)
        self.assertIn('login', r['Location'])

    def test_inject_requires_post(self):
        user = self._operator(self.brand_a)
        self.client.force_login(user)
        r = self.client.get('/admin/dashboard/inject-leads/')
        self.assertEqual(r.status_code, 405)

    @patch('leadgen.services.inject_lead_task')
    def test_operator_can_inject_own_brand_lead(self, mock_task):
        user = self._operator(self.brand_a)
        self.client.force_login(user)
        r = self.client.post('/admin/dashboard/inject-leads/', {
            'buyer_id': str(self.buyer_a.pk), 'lead_ids': [str(self.lead_a.pk)],
        })
        self.assertEqual(r.status_code, 302)
        self.assertTrue(LeadInjection.objects.filter(lead=self.lead_a, buyer=self.buyer_a).exists())
        mock_task.assert_called_once()

    def test_operator_cannot_inject_other_brands_lead(self):
        user = self._operator(self.brand_a)
        self.client.force_login(user)
        r = self.client.post('/admin/dashboard/inject-leads/', {
            'buyer_id': str(self.buyer_a.pk), 'lead_ids': [str(self.lead_b.pk)],
        }, follow=True)
        self.assertFalse(LeadInjection.objects.filter(lead=self.lead_b).exists())

    def test_operator_cannot_use_other_brands_buyer(self):
        user = self._operator(self.brand_a)
        self.client.force_login(user)
        r = self.client.post('/admin/dashboard/inject-leads/', {
            'buyer_id': str(self.buyer_b.pk), 'lead_ids': [str(self.lead_a.pk)],
        })
        self.assertEqual(r.status_code, 404)

    @patch('leadgen.services.inject_lead_task')
    def test_superuser_can_inject_across_brands(self, mock_task):
        owner = User.objects.create_superuser(username='dash_owner2', email='o2@test.com', password='pass')
        self.client.force_login(owner)
        r = self.client.post('/admin/dashboard/inject-leads/', {
            'buyer_id': str(self.buyer_b.pk), 'lead_ids': [str(self.lead_b.pk)],
        })
        self.assertEqual(r.status_code, 302)
        self.assertTrue(LeadInjection.objects.filter(lead=self.lead_b, buyer=self.buyer_b).exists())


class AdminDashboardAffiliateFilterTest(TestCase):
    """The affiliate_id filter on /admin/dashboard/ narrows the leads table
    (and thus what can be selected for injection) to one affiliate's leads."""

    def setUp(self):
        self.brand = _brand('dash-leads-affilter')
        self.affiliate_1 = User.objects.create_user(username='dash_aff1', password='pass')
        self.affiliate_1.profile.role = Profile.Role.AFFILIATE
        self.affiliate_1.profile.brand = self.brand
        self.affiliate_1.profile.save()
        self.affiliate_2 = User.objects.create_user(username='dash_aff2', password='pass')
        self.affiliate_2.profile.role = Profile.Role.AFFILIATE
        self.affiliate_2.profile.brand = self.brand
        self.affiliate_2.profile.save()

        self.lead_1 = Lead.objects.create(
            intake_channel=Lead.CHANNEL_AFFILIATE_API, brand=self.brand, affiliate=self.affiliate_1,
            email='aff1-lead@test.com', phone='+15553330000',
        )
        self.lead_2 = Lead.objects.create(
            intake_channel=Lead.CHANNEL_AFFILIATE_API, brand=self.brand, affiliate=self.affiliate_2,
            email='aff2-lead@test.com', phone='+15554440000',
        )
        # No-affiliate lead (landing page) — must never crash the affiliate
        # dropdown / filter logic that excludes affiliate__isnull leads.
        Lead.objects.create(
            intake_channel=Lead.CHANNEL_LANDING_PAGE, brand=self.brand,
            email='no-affiliate-lead@test.com', phone='+15555550000',
        )

        self.operator = User.objects.create_user(username='dash_op_affilter', password='pass', is_staff=True)
        self.operator.profile.role = Profile.Role.NETWORK_ADMIN
        self.operator.profile.brand = self.brand
        self.operator.profile.save()
        self.client.force_login(self.operator)

    def test_no_filter_shows_all_leads(self):
        r = self.client.get('/admin/dashboard/')
        self.assertContains(r, 'aff1-lead@test.com')
        self.assertContains(r, 'aff2-lead@test.com')
        self.assertContains(r, 'no-affiliate-lead@test.com')

    def test_filter_narrows_to_one_affiliate(self):
        r = self.client.get('/admin/dashboard/', {'affiliate_id': self.affiliate_1.pk})
        self.assertContains(r, 'aff1-lead@test.com')
        self.assertNotContains(r, 'aff2-lead@test.com')
        self.assertNotContains(r, 'no-affiliate-lead@test.com')

    def test_affiliate_dropdown_lists_only_affiliates_with_leads_in_scope(self):
        r = self.client.get('/admin/dashboard/')
        html = r.content.decode()
        self.assertIn('dash_aff1', html)
        self.assertIn('dash_aff2', html)

    def test_invalid_affiliate_id_does_not_crash(self):
        r = self.client.get('/admin/dashboard/', {'affiliate_id': 'not-a-number'})
        self.assertEqual(r.status_code, 200)
