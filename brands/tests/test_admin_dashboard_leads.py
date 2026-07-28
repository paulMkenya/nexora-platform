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
