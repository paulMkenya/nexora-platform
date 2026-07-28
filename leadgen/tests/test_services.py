"""Tests for leadgen/services.py — the shared synchronous-injection helper
used by the Django admin action, affiliate My Leads page, and the operator
dashboard's embedded inject section."""
from unittest.mock import MagicMock, patch

import pytest

from leadgen.models import Lead, LeadInjection
from leadgen.services import inject_leads_to_buyer, summarize_injection_results


def _lead(**kwargs):
    defaults = dict(intake_channel=Lead.CHANNEL_LANDING_PAGE, email='svc@test.com', phone='+15551234567')
    defaults.update(kwargs)
    return Lead.objects.create(**defaults)


@pytest.mark.django_db
class TestInjectLeadsToBuyer:
    def test_creates_one_injection_per_lead(self, buyer):
        leads = [_lead(email=f'svc{i}@test.com') for i in range(3)]
        with patch('leadgen.services.inject_lead_task') as mock_task:
            results = inject_leads_to_buyer(leads, buyer)
        assert len(results) == 3
        assert LeadInjection.objects.filter(buyer=buyer).count() == 3
        assert mock_task.call_count == 3

    def test_returns_lead_injection_pairs_in_order(self, buyer):
        leads = [_lead(email=f'order{i}@test.com') for i in range(2)]
        with patch('leadgen.services.inject_lead_task'):
            results = inject_leads_to_buyer(leads, buyer)
        assert [lead for lead, _ in results] == leads

    def test_swallows_retry_exception_from_task(self, buyer):
        lead = _lead()
        with patch('leadgen.services.inject_lead_task', side_effect=Exception('Retry')):
            results = inject_leads_to_buyer([lead], buyer)
        assert len(results) == 1  # did not raise/crash the caller
        _, injection = results[0]
        assert injection.pk is not None


@pytest.mark.django_db
class TestSummarizeInjectionResults:
    def _fake_result(self, status):
        lead = _lead(email=f'{status}@test.com')
        injection = MagicMock(status=status)
        return (lead, injection)

    def test_counts_by_status(self):
        results = [
            self._fake_result(LeadInjection.STATUS_DELIVERED),
            self._fake_result(LeadInjection.STATUS_DELIVERED),
            self._fake_result(LeadInjection.STATUS_DUPLICATE),
            self._fake_result(LeadInjection.STATUS_FAILED),
            self._fake_result(LeadInjection.STATUS_PENDING),  # counts as "failed" bucket (not yet delivered)
        ]
        delivered, duplicate, failed = summarize_injection_results(results)
        assert (delivered, duplicate, failed) == (2, 1, 2)

    def test_empty_results(self):
        assert summarize_injection_results([]) == (0, 0, 0)
