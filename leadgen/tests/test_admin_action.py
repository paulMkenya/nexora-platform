"""Tests for the Django admin 'inject to buyer' bulk action on LeadAdmin
(leadgen/admin.py) — intermediate confirmation page, then synchronous
injection on confirm."""
from unittest.mock import patch

import pytest
from django.contrib.admin import helpers
from django.contrib.auth import get_user_model
from django.test import Client

from leadgen.models import Lead, LeadInjection

User = get_user_model()


@pytest.fixture
def superuser(db):
    return User.objects.create_superuser(username='leadadmin', email='leadadmin@test.com', password='pass')


@pytest.fixture(autouse=True)
def _platform_admin_host(settings):
    # Real Django admin URLs are locked to PLATFORM_ADMIN_HOSTS (see
    # brands/tests/test_admin_domain_lockdown.py) — the test client's default
    # Host ('testserver') must be allow-listed or every /admin/... request
    # 302s away before reaching the view under test.
    settings.PLATFORM_ADMIN_HOSTS = ['testserver']


@pytest.mark.django_db
class TestInjectToBuyerAction:
    def _lead(self):
        return Lead.objects.create(
            intake_channel=Lead.CHANNEL_LANDING_PAGE, email='admin-action@test.com', phone='+15551234567')

    def test_intermediate_page_renders_buyer_choices(self, superuser, buyer):
        client = Client()
        client.force_login(superuser)
        lead = self._lead()
        r = client.post('/admin/leadgen/lead/', {
            'action': 'inject_to_buyer',
            helpers.ACTION_CHECKBOX_NAME: [str(lead.pk)],
        })
        assert r.status_code == 200
        assert str(buyer.pk).encode() in r.content
        assert buyer.name.encode() in r.content

    @patch('leadgen.services.inject_lead_task')
    def test_confirm_creates_injection(self, mock_task, superuser, buyer):
        client = Client()
        client.force_login(superuser)
        lead = self._lead()
        r = client.post('/admin/leadgen/lead/', {
            'action': 'inject_to_buyer',
            helpers.ACTION_CHECKBOX_NAME: [str(lead.pk)],
            'apply': '1',
            'buyer_id': str(buyer.pk),
        }, follow=True)
        assert r.status_code == 200
        assert LeadInjection.objects.filter(lead=lead, buyer=buyer).exists()
        mock_task.assert_called_once()

    def test_inactive_buyer_rejected(self, superuser, buyer):
        buyer.is_active = False
        buyer.save(update_fields=['is_active'])
        client = Client()
        client.force_login(superuser)
        lead = self._lead()
        client.post('/admin/leadgen/lead/', {
            'action': 'inject_to_buyer',
            helpers.ACTION_CHECKBOX_NAME: [str(lead.pk)],
            'apply': '1',
            'buyer_id': str(buyer.pk),
        }, follow=True)
        assert not LeadInjection.objects.filter(lead=lead).exists()

    @patch('leadgen.services.inject_lead_task')
    def test_multiple_selected_leads_all_injected(self, mock_task, superuser, buyer):
        client = Client()
        client.force_login(superuser)
        leads = [self._lead() for _ in range(3)]
        client.post('/admin/leadgen/lead/', {
            'action': 'inject_to_buyer',
            helpers.ACTION_CHECKBOX_NAME: [str(lead.pk) for lead in leads],
            'apply': '1',
            'buyer_id': str(buyer.pk),
        }, follow=True)
        assert LeadInjection.objects.filter(lead__in=leads, buyer=buyer).count() == 3
        assert mock_task.call_count == 3
