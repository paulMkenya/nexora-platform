"""Tests for smartlinks.admin.RoutingRuleInlineForm — RoutingRule.countries
is stored as a comma-separated ISO-alpha-2 string (see the model field's
help_text), so the admin inline form uses user_profile.geo.CountryListField
to render a real multi-select and convert to/from that CSV shape on save."""
from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings

from countries_plus.models import Country

from smartlinks.admin import RoutingRuleInlineForm
from smartlinks.models import RoutingRule, SmartLink

User = get_user_model()


class RoutingRuleInlineFormCountriesTest(TestCase):
    def setUp(self):
        Country.objects.get_or_create(
            iso='US', defaults={'name': 'United States', 'iso3': 'USA', 'iso_numeric': 840})
        Country.objects.get_or_create(
            iso='GB', defaults={'name': 'United Kingdom', 'iso3': 'GBR', 'iso_numeric': 826})
        self.smart_link = SmartLink.objects.create(name='Test', alias='test-inline-form')

    def test_selected_countries_serialize_to_csv_on_save(self):
        form = RoutingRuleInlineForm(data={
            'smart_link': self.smart_link.pk,
            'priority': 100,
            'destination_url': 'https://dest.example',
            'countries': ['US', 'GB'],
            'device_type': 'any',
            'is_active': 'on',
        })
        self.assertTrue(form.is_valid(), form.errors)
        rule = form.save(commit=False)
        rule.smart_link = self.smart_link
        rule.save()
        rule.refresh_from_db()
        self.assertEqual(rule.countries, 'US,GB')

    def test_stored_csv_prefills_the_multiselect(self):
        rule = RoutingRule.objects.create(
            smart_link=self.smart_link, priority=100, destination_url='https://dest.example',
            countries='US,GB')
        form = RoutingRuleInlineForm(instance=rule)
        rendered = str(form['countries'])
        self.assertIn('value="US" selected', rendered)
        self.assertIn('value="GB" selected', rendered)

    def test_empty_countries_matches_any_and_round_trips_to_blank(self):
        form = RoutingRuleInlineForm(data={
            'smart_link': self.smart_link.pk,
            'priority': 100,
            'destination_url': 'https://dest.example',
            'countries': [],
            'device_type': 'any',
            'is_active': 'on',
        })
        self.assertTrue(form.is_valid(), form.errors)
        rule = form.save(commit=False)
        rule.smart_link = self.smart_link
        rule.save()
        rule.refresh_from_db()
        self.assertEqual(rule.countries, '')


@override_settings(PLATFORM_ADMIN_HOSTS=['testserver'])
class SmartLinkAdminInlineRendersDropdownTest(TestCase):
    def setUp(self):
        Country.objects.get_or_create(
            iso='US', defaults={'name': 'United States', 'iso3': 'USA', 'iso_numeric': 840})
        self.superuser = User.objects.create_superuser(
            username='smartlinkadmin', email='smartlinkadmin@test.com', password='pass')

    def test_smartlink_add_form_renders_countries_multiselect(self):
        client = Client()
        client.force_login(self.superuser)
        r = client.get('/admin/smartlinks/smartlink/add/')
        self.assertEqual(r.status_code, 200)
        self.assertIn(b'United States (US)', r.content)
