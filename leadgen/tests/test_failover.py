"""Tests for leadgen/failover.py — _next_untried_buyer and advance_chain
in isolation, mocking leadgen.services.start_injection so these tests
verify the orchestration decision (who's next, or is the chain done)
without touching HTTP/Celery. See test_tasks.py's TestChainManagedInjection
for the full end-to-end integration (real inject_lead_task hook)."""
from unittest.mock import patch

import pytest

from leadgen.failover import _next_untried_buyer, advance_chain
from leadgen.models import Lead, LeadBuyer, LeadInjection, RoutingRule


def _lead(brand=None, **kwargs):
    defaults = dict(intake_channel=Lead.CHANNEL_LANDING_PAGE, email='fo@test.com', phone='+15551234567')
    defaults.update(kwargs)
    return Lead.objects.create(brand=brand, **defaults)


def _rule(brand, buyer, **kwargs):
    defaults = dict(priority=100, is_active=True)
    defaults.update(kwargs)
    return RoutingRule.objects.create(brand=brand, buyer=buyer, **defaults)


@pytest.mark.django_db
class TestNextUntriedBuyer:
    def test_returns_first_buyer_when_none_tried(self, buyer):
        other = LeadBuyer.objects.create(name='O', slug='fo-other1', is_active=True, base_url='https://o.test')
        lead = _lead()
        assert _next_untried_buyer(lead, [buyer, other]) == buyer

    def test_skips_buyer_with_an_existing_injection(self, buyer):
        other = LeadBuyer.objects.create(name='O2', slug='fo-other2', is_active=True, base_url='https://o2.test')
        lead = _lead()
        LeadInjection.objects.create(lead=lead, buyer=buyer)
        assert _next_untried_buyer(lead, [buyer, other]) == other

    def test_returns_none_when_every_buyer_tried(self, buyer):
        lead = _lead()
        LeadInjection.objects.create(lead=lead, buyer=buyer)
        assert _next_untried_buyer(lead, [buyer]) is None

    def test_empty_chain_returns_none(self, buyer):
        lead = _lead()
        assert _next_untried_buyer(lead, []) is None


@pytest.mark.django_db
class TestAdvanceChain:
    def test_already_injected_lead_is_a_noop(self, brand, buyer):
        lead = _lead(brand=brand, status=Lead.STATUS_INJECTED)
        _rule(brand, buyer)
        with patch('leadgen.services.start_injection') as mock_start:
            advance_chain(lead.pk)
        mock_start.assert_not_called()

    def test_already_deposit_lead_is_a_noop(self, brand, buyer):
        lead = _lead(brand=brand, status=Lead.STATUS_DEPOSIT)
        _rule(brand, buyer)
        with patch('leadgen.services.start_injection') as mock_start:
            advance_chain(lead.pk)
        mock_start.assert_not_called()

    def test_empty_chain_marks_unrouted_immediately(self, brand):
        lead = _lead(brand=brand)  # no RoutingRule at all
        with patch('leadgen.services.start_injection') as mock_start:
            advance_chain(lead.pk)
        mock_start.assert_not_called()
        lead.refresh_from_db()
        assert lead.status == Lead.STATUS_UNROUTED

    def test_starts_injection_on_first_untried_buyer(self, brand, buyer):
        lead = _lead(brand=brand)
        _rule(brand, buyer)
        with patch('leadgen.services.start_injection') as mock_start:
            advance_chain(lead.pk)
        mock_start.assert_called_once_with(lead, buyer, synchronous=False, chain_managed=True)

    def test_advances_past_an_already_tried_buyer(self, brand, buyer):
        other = LeadBuyer.objects.create(name='O3', slug='fo-other3', is_active=True, base_url='https://o3.test')
        lead = _lead(brand=brand)
        _rule(brand, buyer, priority=1)
        _rule(brand, other, priority=2)
        LeadInjection.objects.create(lead=lead, buyer=buyer, chain_managed=True)  # buyer already attempted
        with patch('leadgen.services.start_injection') as mock_start:
            advance_chain(lead.pk)
        mock_start.assert_called_once_with(lead, other, synchronous=False, chain_managed=True)

    def test_chain_exhausted_marks_unrouted(self, brand, buyer):
        lead = _lead(brand=brand)
        _rule(brand, buyer)
        LeadInjection.objects.create(lead=lead, buyer=buyer, chain_managed=True, status=LeadInjection.STATUS_FAILED)
        with patch('leadgen.services.start_injection') as mock_start:
            advance_chain(lead.pk)
        mock_start.assert_not_called()
        lead.refresh_from_db()
        assert lead.status == Lead.STATUS_UNROUTED

    def test_missing_lead_is_a_noop(self):
        with patch('leadgen.services.start_injection') as mock_start:
            advance_chain(999999)  # must not raise
        mock_start.assert_not_called()

    def test_double_trigger_does_not_double_send(self, brand, buyer):
        """Calling advance_chain twice back-to-back for a lead that hasn't
        moved on yet (still one untried buyer) must not start two
        injections against the same buyer."""
        lead = _lead(brand=brand)
        _rule(brand, buyer)
        with patch('leadgen.services.start_injection') as mock_start:
            mock_start.side_effect = lambda started_lead, started_buyer, **kw: (
                LeadInjection.objects.create(
                    lead=started_lead, buyer=started_buyer, chain_managed=True))
            advance_chain(lead.pk)
            advance_chain(lead.pk)  # second call — buyer now has an injection, must be skipped
        assert mock_start.call_count == 1
