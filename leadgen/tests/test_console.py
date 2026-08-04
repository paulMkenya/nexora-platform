"""Tests for the Distribution console (Phase 3 of the lead-distribution
build) — leadgen/admin_views.py, leadgen/admin_urls.py. Brand scoping
mirrors brands/tests/test_admin_dashboard_leads.py's conventions exactly
(the console is a sibling surface to the operator dashboard)."""
from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth import get_user_model
from django.test import TestCase

from brands.models import Brand
from leadgen.models import BoxType, Lead, LeadBuyer, LeadInjection, RoutingRule
from user_profile.models import Profile

User = get_user_model()


def _brand(slug):
    return Brand.objects.create(
        slug=slug, name=slug, primary_domain=f'{slug}.example.com',
        tracking_domain=f't.{slug}.example.com',
    )


class ConsoleBrandScopingTest(TestCase):
    def setUp(self):
        self.brand_a = _brand('console-a')
        self.brand_b = _brand('console-b')
        self.box_type = BoxType.objects.create(
            name='Console Test Box', slug='console-test-box',
            connector_class='leadgen.connectors.LeadBuyerConnector',
            auth_type=BoxType.AUTH_API_KEY_QUERY, auth_param_name='apiKey',
            single_endpoint_path='/leads', batch_endpoint_path='',
            fetch_endpoint_path='/leads', batch_max_size=1,
            rate_limit_burst=10, rate_limit_refill_tokens=1, rate_limit_refill_seconds=1,
        )
        self.buyer_a = LeadBuyer.objects.create(
            brand=self.brand_a, box_type=self.box_type, name='Buyer A', slug='console-buyer-a',
            is_active=True, base_url='https://buyer-a.test',
        )
        self.buyer_b = LeadBuyer.objects.create(
            brand=self.brand_b, box_type=self.box_type, name='Buyer B', slug='console-buyer-b',
            is_active=True, base_url='https://buyer-b.test',
        )
        self.lead_a = Lead.objects.create(
            intake_channel=Lead.CHANNEL_LANDING_PAGE, brand=self.brand_a,
            email='console-lead-a@test.com', phone='+15551110000',
        )
        self.lead_b = Lead.objects.create(
            intake_channel=Lead.CHANNEL_LANDING_PAGE, brand=self.brand_b,
            email='console-lead-b@test.com', phone='+15552220000',
        )
        self.rule_a = RoutingRule.objects.create(
            brand=self.brand_a, buyer=self.buyer_a, priority=1, is_active=True, name='Rule A')

    def _operator(self, brand):
        user = User.objects.create_user(username=f'console_op_{brand.slug}', password='pass', is_staff=True)
        user.profile.role = Profile.Role.NETWORK_ADMIN
        user.profile.brand = brand
        user.profile.save()
        return user

    def _owner(self):
        return User.objects.create_superuser(username='console_owner', email='o@test.com', password='pass')

    # --- leads console ---

    def test_operator_sees_only_own_brand_leads(self):
        self.client.force_login(self._operator(self.brand_a))
        r = self.client.get('/admin/distribution/leads/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'console-lead-a@test.com')
        self.assertNotContains(r, 'console-lead-b@test.com')

    def test_owner_sees_all_brands_leads(self):
        self.client.force_login(self._owner())
        r = self.client.get('/admin/distribution/leads/')
        self.assertContains(r, 'console-lead-a@test.com')
        self.assertContains(r, 'console-lead-b@test.com')

    def test_computed_chain_shown_for_matching_lead(self):
        self.client.force_login(self._operator(self.brand_a))
        r = self.client.get('/admin/distribution/leads/')
        self.assertContains(r, 'Buyer A')

    def test_lead_with_no_matching_rule_shows_no_match(self):
        self.client.force_login(self._operator(self.brand_b))
        r = self.client.get('/admin/distribution/leads/')
        self.assertContains(r, 'no matching rule')

    def test_status_filter(self):
        Lead.objects.filter(pk=self.lead_a.pk).update(status=Lead.STATUS_UNROUTED)
        self.client.force_login(self._operator(self.brand_a))
        r = self.client.get('/admin/distribution/leads/', {'status': Lead.STATUS_UNROUTED})
        self.assertContains(r, 'console-lead-a@test.com')
        r2 = self.client.get('/admin/distribution/leads/', {'status': Lead.STATUS_INJECTED})
        self.assertNotContains(r2, 'console-lead-a@test.com')

    def test_empty_state_when_no_leads(self):
        Lead.objects.all().delete()
        self.client.force_login(self._owner())
        r = self.client.get('/admin/distribution/leads/')
        self.assertContains(r, 'No leads captured yet')

    def test_anonymous_redirected(self):
        r = self.client.get('/admin/distribution/leads/')
        self.assertEqual(r.status_code, 302)

    # --- route now ---

    def test_route_now_requires_post(self):
        self.client.force_login(self._operator(self.brand_a))
        r = self.client.get('/admin/distribution/leads/route-now/')
        self.assertEqual(r.status_code, 405)

    @patch('leadgen.services.inject_lead_task')
    def test_route_now_creates_chain_managed_injection(self, mock_task):
        self.client.force_login(self._operator(self.brand_a))
        r = self.client.post('/admin/distribution/leads/route-now/', {'lead_ids': [str(self.lead_a.pk)]})
        self.assertEqual(r.status_code, 302)
        injection = LeadInjection.objects.filter(lead=self.lead_a, buyer=self.buyer_a).first()
        self.assertIsNotNone(injection)
        self.assertTrue(injection.chain_managed)

    def test_route_now_cannot_touch_other_brands_lead(self):
        self.client.force_login(self._operator(self.brand_a))
        self.client.post('/admin/distribution/leads/route-now/', {'lead_ids': [str(self.lead_b.pk)]})
        self.assertFalse(LeadInjection.objects.filter(lead=self.lead_b).exists())

    def test_route_now_no_leads_selected_shows_error(self):
        self.client.force_login(self._operator(self.brand_a))
        r = self.client.post('/admin/distribution/leads/route-now/', {}, follow=True)
        messages = list(r.context['messages'])
        self.assertTrue(any('Select at least one' in str(m) for m in messages))

    # --- buyers ---

    def test_operator_sees_only_own_brand_and_platform_wide_buyers(self):
        LeadBuyer.objects.create(
            box_type=self.box_type,
            name='Platform Buyer', slug='console-platform-buyer', is_active=True, base_url='https://p.test')
        self.client.force_login(self._operator(self.brand_a))
        r = self.client.get('/admin/distribution/buyers/')
        self.assertContains(r, 'Buyer A')
        self.assertContains(r, 'Platform Buyer')
        self.assertNotContains(r, 'Buyer B')

    def test_operator_cannot_edit_other_brands_buyer(self):
        self.client.force_login(self._operator(self.brand_a))
        r = self.client.get(f'/admin/distribution/buyers/{self.buyer_b.pk}/edit/')
        self.assertEqual(r.status_code, 404)

    def test_operator_create_form_locks_brand_to_own(self):
        operator = self._operator(self.brand_a)
        self.client.force_login(operator)
        r = self.client.get('/admin/distribution/buyers/add/')
        form = r.context['form']
        self.assertEqual(list(form.fields['brand'].queryset), [self.brand_a])

    def test_create_buyer_via_console(self):
        self.client.force_login(self._operator(self.brand_a))
        r = self.client.post('/admin/distribution/buyers/add/', {
            'brand': self.brand_a.pk, 'box_type': self.box_type.pk,
            'name': 'New Console Buyer', 'slug': 'new-console-buyer',
            'is_active': 'on', 'auto_inject': '', 'base_url': 'https://new.test',
            'api_key': 'secret123', 'field_mapping': '{}',
        })
        self.assertEqual(r.status_code, 302)
        buyer = LeadBuyer.objects.filter(slug='new-console-buyer').first()
        self.assertIsNotNone(buyer)
        self.assertEqual(buyer.get_api_key(), 'secret123')

    # --- test connection (Phase 5) ---

    def test_test_connection_requires_post(self):
        self.client.force_login(self._operator(self.brand_a))
        r = self.client.get(f'/admin/distribution/buyers/{self.buyer_a.pk}/test-connection/')
        self.assertEqual(r.status_code, 405)

    def test_operator_cannot_test_connection_for_other_brands_buyer(self):
        self.client.force_login(self._operator(self.brand_a))
        r = self.client.post(f'/admin/distribution/buyers/{self.buyer_b.pk}/test-connection/')
        self.assertEqual(r.status_code, 404)

    @patch('leadgen.connectors.requests.request')
    def test_test_connection_success_shows_payload_and_response(self, mock_req):
        mock_req.return_value = MagicMock(
            ok=True, content=b'{}',
            json=lambda: {'addedLeads': [{'id': 'ext-test-1'}], 'failedToAddLeads': []},
        )
        self.client.force_login(self._operator(self.brand_a))
        r = self.client.post(f'/admin/distribution/buyers/{self.buyer_a.pk}/test-connection/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Test connection succeeded')
        self.assertContains(r, 'ext-test-1')
        # the synthetic test lead, not a real one, was sent
        sent_json = mock_req.call_args.kwargs.get('json') or {}
        self.assertIn('TestConnection', str(sent_json))

    @patch('leadgen.connectors.requests.request')
    def test_test_connection_failure_shows_error(self, mock_req):
        mock_req.return_value = MagicMock(ok=False, status_code=401, text='invalid api key', content=b'x')
        self.client.force_login(self._operator(self.brand_a))
        r = self.client.post(f'/admin/distribution/buyers/{self.buyer_a.pk}/test-connection/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Test connection failed')
        self.assertContains(r, '401')

    @patch('leadgen.connectors.requests.request')
    def test_test_connection_never_creates_a_lead_or_injection(self, mock_req):
        mock_req.return_value = MagicMock(
            ok=True, content=b'{}', json=lambda: {'addedLeads': [{'id': 'ext-test-2'}], 'failedToAddLeads': []})
        lead_count_before = Lead.objects.count()
        injection_count_before = LeadInjection.objects.count()
        self.client.force_login(self._operator(self.brand_a))
        self.client.post(f'/admin/distribution/buyers/{self.buyer_a.pk}/test-connection/')
        self.assertEqual(Lead.objects.count(), lead_count_before)
        self.assertEqual(LeadInjection.objects.count(), injection_count_before)

    # --- routing rules ---

    def test_operator_sees_only_own_brand_rules(self):
        RoutingRule.objects.create(brand=self.brand_b, buyer=self.buyer_b, name='Rule B', is_active=True)
        self.client.force_login(self._operator(self.brand_a))
        r = self.client.get('/admin/distribution/routing-rules/')
        self.assertContains(r, 'Rule A')
        self.assertNotContains(r, 'Rule B')

    def test_operator_cannot_edit_other_brands_rule(self):
        rule_b = RoutingRule.objects.create(brand=self.brand_b, buyer=self.buyer_b, name='Rule B')
        self.client.force_login(self._operator(self.brand_a))
        r = self.client.get(f'/admin/distribution/routing-rules/{rule_b.pk}/edit/')
        self.assertEqual(r.status_code, 404)

    def test_create_rule_via_console_defaults_inactive(self):
        self.client.force_login(self._operator(self.brand_a))
        r = self.client.post('/admin/distribution/routing-rules/add/', {
            'brand': self.brand_a.pk, 'name': 'Console New Rule', 'buyer': self.buyer_a.pk,
            'priority': '100', 'offer': '', 'country_iso2': '', 'affiliate': '',
            'vertical': '', 'source_channel': '',
        })
        self.assertEqual(r.status_code, 302)
        rule = RoutingRule.objects.filter(name='Console New Rule').first()
        self.assertIsNotNone(rule)
        self.assertFalse(rule.is_active)

    def test_rule_form_warns_bought_traffic_has_no_live_channel(self):
        """Phase 6: same help_text check as test_routing_admin.py, on the
        console surface (RoutingRuleForm shares the model field, so this
        should already pass — confirms the two surfaces don't drift)."""
        self.client.force_login(self._operator(self.brand_a))
        r = self.client.get('/admin/distribution/routing-rules/add/')
        self.assertContains(r, 'no live intake path yet')


@pytest.mark.django_db
def test_navigation_includes_distribution_group():
    """Registry-level check (nexora/navigation.py) — the console's nav
    entries actually resolve, independent of any view rendering."""
    from nexora.navigation import nav_for
    groups = nav_for('admin', is_platform_owner=True)
    group_labels = [g.label for g in groups]
    assert 'Distribution' in group_labels
    distribution = next(g for g in groups if g.label == 'Distribution')
    item_labels = [item.label for item in distribution.items]
    assert item_labels == ['Leads', 'Buyers', 'Routing Rules', 'Affiliate Integrations']
