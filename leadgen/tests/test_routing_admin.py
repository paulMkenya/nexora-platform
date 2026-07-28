"""Smoke tests confirming RoutingRule is actually usable through the Django
admin — the guide's Phase 1 deliverable is 'the engine + admin to create
rules', not just the model/resolver."""
import pytest
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
