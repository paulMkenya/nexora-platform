"""Tests for the inject_pending_leads management command — previously
untested; added while refactoring it onto services.start_injection()."""
from io import StringIO
from unittest.mock import patch

import pytest
from django.core.management import call_command

from leadgen.models import Lead, LeadBuyer, LeadInjection


def _lead(buyer=None, **kwargs):
    """In the buyer's brand when one is given — the command injects, and
    start_injection refuses a cross-brand delivery."""
    defaults = dict(intake_channel=Lead.CHANNEL_LANDING_PAGE, email='cmd@test.com', phone='+15551234567')
    if buyer is not None:
        defaults['brand'] = buyer.brand
    defaults.update(kwargs)
    return Lead.objects.create(**defaults)


@pytest.mark.django_db
class TestInjectPendingLeadsCommand:
    def test_enqueues_new_leads_via_delay(self, buyer):
        lead = _lead(buyer)
        with patch('leadgen.services.inject_lead_task') as mock_task:
            call_command('inject_pending_leads', stdout=StringIO())
        assert LeadInjection.objects.filter(lead=lead, buyer=buyer).exists()
        mock_task.delay.assert_called_once()
        mock_task.assert_not_called()  # queued, not run inline

    def test_skips_leads_with_no_buyer_configured(self):
        LeadBuyer.objects.all().delete()
        lead = _lead(email='no-buyer@test.com')
        out = StringIO()
        with patch('leadgen.services.inject_lead_task'):
            call_command('inject_pending_leads', stdout=out)
        assert not LeadInjection.objects.filter(lead=lead).exists()
        assert 'skipped (no buyer configured)' in out.getvalue()

    def test_buyer_filter_skips_leads_resolving_to_a_different_buyer(self, buyer):
        # 'Aaa Buyer' sorts before the 'buyer' fixture's 'Test Buyer'
        # (LeadBuyer.Meta.ordering = ('name',)), so resolve_buyer_for_lead
        # picks THIS one by default — the lead never actually resolves to
        # `buyer`, so filtering for --buyer=<buyer.slug> must skip it.
        LeadBuyer.objects.create(
            name='Aaa Buyer', slug='cmd-other-buyer', is_active=True,
            base_url='https://other.test', brand=buyer.brand)
        lead = _lead(buyer, email='filtered@test.com')
        with patch('leadgen.services.inject_lead_task'):
            call_command('inject_pending_leads', buyer=buyer.slug, stdout=StringIO())
        assert not LeadInjection.objects.filter(lead=lead, buyer=buyer).exists()

    def test_leads_with_pending_injection_are_not_re_enqueued(self, buyer):
        lead = _lead(buyer, email='already-pending@test.com')
        LeadInjection.objects.create(lead=lead, buyer=buyer, status=LeadInjection.STATUS_PENDING)
        with patch('leadgen.services.inject_lead_task') as mock_task:
            call_command('inject_pending_leads', stdout=StringIO())
        mock_task.delay.assert_not_called()

    def test_respects_limit(self, buyer):
        for i in range(5):
            _lead(buyer, email=f'limit{i}@test.com')
        with patch('leadgen.services.inject_lead_task'):
            call_command('inject_pending_leads', limit=2, stdout=StringIO())
        assert LeadInjection.objects.filter(buyer=buyer).count() == 2
