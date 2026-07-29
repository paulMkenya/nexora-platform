"""Smoke tests confirming RoutingRule is actually usable through the Django
admin — the guide's Phase 1 deliverable is 'the engine + admin to create
rules', not just the model/resolver."""
import pytest
from countries_plus.models import Country
from django.contrib.auth import get_user_model
from django.test import Client

from leadgen.models import RoutingRule

User = get_user_model()


@pytest.fixture
def superuser(db):
    return User.objects.create_superuser(username='routeadmin', email='routeadmin@test.com', password='pass')


@pytest.fixture(autouse=True)
def _platform_admin_host(settings):
    # Real Django admin URLs are locked to PLATFORM_ADMIN_HOSTS (see
    # brands/tests/test_admin_domain_lockdown.py).
    settings.PLATFORM_ADMIN_HOSTS = ['testserver']


@pytest.mark.django_db
class TestRoutingRuleAdmin:
    def test_changelist_loads(self, superuser):
        client = Client()
        client.force_login(superuser)
        r = client.get('/admin/leadgen/routingrule/')
        assert r.status_code == 200

    def test_add_form_loads(self, superuser):
        client = Client()
        client.force_login(superuser)
        r = client.get('/admin/leadgen/routingrule/add/')
        assert r.status_code == 200

    def test_add_form_warns_bought_traffic_has_no_live_channel(self, superuser):
        """Phase 6: RoutingRule.source_channel's help_text (single field
        definition, shared by admin + the console form) must warn that
        'bought' has no live intake path yet, so an operator can't build a
        rule around it believing it'll ever match a lead."""
        client = Client()
        client.force_login(superuser)
        r = client.get('/admin/leadgen/routingrule/add/')
        assert r.status_code == 200
        assert b'no live intake path yet' in r.content

    def test_create_rule_via_admin_defaults_to_inactive(self, superuser, brand, buyer):
        client = Client()
        client.force_login(superuser)
        r = client.post('/admin/leadgen/routingrule/add/', {
            'brand': brand.pk,
            'buyer': buyer.pk,
            'priority': 100,
            'name': 'Admin-created test rule',
            'offer': '', 'country_iso2': '', 'affiliate': '', 'vertical': '', 'source_channel': '',
            # is_active intentionally omitted — an unchecked checkbox submits nothing
        }, follow=True)
        assert r.status_code == 200
        rule = RoutingRule.objects.get(name='Admin-created test rule')
        assert rule.is_active is False  # the kill-switch posture — never on by default
        assert rule.brand_id == brand.pk
        assert rule.buyer_id == buyer.pk

    def test_country_iso2_renders_as_a_dropdown_with_real_countries(self, superuser):
        """country_iso2 gets its choices from user_profile.geo.country_choices
        (sourced from countries_plus) — a plain function reference on the
        model field, so both admin and the console form render a <select>
        with zero form/template changes. countries_plus isn't seeded in a
        fresh test DB (see brands/tests/test_advertiser_onboarding.py), so
        seed one row here to prove real data flows through end to end."""
        Country.objects.create(iso='US', name='United States', iso3='USA', iso_numeric=840)
        client = Client()
        client.force_login(superuser)
        r = client.get('/admin/leadgen/routingrule/add/')
        assert r.status_code == 200
        assert b'<select name="country_iso2"' in r.content
        assert b'United States (US)' in r.content
