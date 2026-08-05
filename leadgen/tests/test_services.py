"""Tests for leadgen/services.py — the shared synchronous-injection helper
used by the Django admin action, affiliate My Leads page, and the operator
dashboard's embedded inject section."""
from unittest.mock import MagicMock, patch

import pytest

from leadgen.models import Lead, LeadInjection
from leadgen.services import (
    attach_latest_injections, inject_leads_to_buyer, start_injection, summarize_injection_results,
)


def _lead(buyer, **kwargs):
    """A lead in the buyer's own brand. start_injection refuses a
    cross-brand delivery (Paul's ruling, 2026-08-05), so a test lead that
    is going to be injected must belong to the same brand as its buyer."""
    defaults = dict(
        brand=buyer.brand, intake_channel=Lead.CHANNEL_LANDING_PAGE,
        email='svc@test.com', phone='+15551234567')
    defaults.update(kwargs)
    return Lead.objects.create(**defaults)


@pytest.mark.django_db
class TestStartInjection:
    """The one shared primitive every injection entry point (auto-inject,
    the management command, every manual UI surface) now funnels through."""

    def test_synchronous_runs_inline_and_refreshes(self, buyer):
        lead = _lead(buyer)
        with patch('leadgen.services.inject_lead_task') as mock_task:
            injection = start_injection(lead, buyer, synchronous=True)
        mock_task.assert_called_once_with(injection.pk)
        mock_task.delay.assert_not_called()

    def test_asynchronous_queues_via_delay(self, buyer):
        lead = _lead(buyer)
        with patch('leadgen.services.inject_lead_task') as mock_task:
            injection = start_injection(lead, buyer, synchronous=False)
        mock_task.delay.assert_called_once_with(injection.pk)
        mock_task.assert_not_called()  # never run inline

    def test_creates_the_injection_row_either_way(self, buyer):
        lead = _lead(buyer)
        with patch('leadgen.services.inject_lead_task'):
            injection = start_injection(lead, buyer, synchronous=False)
        assert LeadInjection.objects.filter(pk=injection.pk, lead=lead, buyer=buyer).exists()

    def test_synchronous_swallows_retry_exception(self, buyer):
        lead = _lead(buyer)
        with patch('leadgen.services.inject_lead_task', side_effect=Exception('Retry')):
            injection = start_injection(lead, buyer, synchronous=True)  # must not raise
        assert injection.pk is not None


@pytest.mark.django_db
class TestInjectLeadsToBuyer:
    def test_creates_one_injection_per_lead(self, buyer):
        leads = [_lead(buyer, email=f'svc{i}@test.com') for i in range(3)]
        with patch('leadgen.services.inject_lead_task') as mock_task:
            results = inject_leads_to_buyer(leads, buyer)
        assert len(results) == 3
        assert LeadInjection.objects.filter(buyer=buyer).count() == 3
        assert mock_task.call_count == 3

    def test_returns_lead_injection_pairs_in_order(self, buyer):
        leads = [_lead(buyer, email=f'order{i}@test.com') for i in range(2)]
        with patch('leadgen.services.inject_lead_task'):
            results = inject_leads_to_buyer(leads, buyer)
        assert [lead for lead, _ in results] == leads

    def test_swallows_retry_exception_from_task(self, buyer):
        lead = _lead(buyer)
        with patch('leadgen.services.inject_lead_task', side_effect=Exception('Retry')):
            results = inject_leads_to_buyer([lead], buyer)
        assert len(results) == 1  # did not raise/crash the caller
        _, injection = results[0]
        assert injection.pk is not None


@pytest.mark.django_db
class TestSummarizeInjectionResults:
    def _fake_result(self, status, buyer):
        lead = _lead(buyer, email=f'{status}@test.com')
        injection = MagicMock(status=status)
        return (lead, injection)

    def test_counts_by_status(self, buyer):
        results = [
            self._fake_result(LeadInjection.STATUS_DELIVERED, buyer),
            self._fake_result(LeadInjection.STATUS_DELIVERED, buyer),
            self._fake_result(LeadInjection.STATUS_DUPLICATE, buyer),
            self._fake_result(LeadInjection.STATUS_FAILED, buyer),
            self._fake_result(LeadInjection.STATUS_PENDING, buyer),  # "failed" bucket (not yet delivered)
        ]
        delivered, duplicate, failed = summarize_injection_results(results)
        assert (delivered, duplicate, failed) == (2, 1, 2)

    def test_empty_results(self):
        assert summarize_injection_results([]) == (0, 0, 0)


@pytest.mark.django_db
class TestAttachLatestInjections:
    def test_attaches_most_recent_injection_per_lead(self, buyer):
        lead = _lead(buyer)
        older = LeadInjection.objects.create(lead=lead, buyer=buyer, status=LeadInjection.STATUS_FAILED)
        newer = LeadInjection.objects.create(lead=lead, buyer=buyer, status=LeadInjection.STATUS_DELIVERED)
        # created_at is auto_now_add — force explicit ordering rather than
        # relying on same-microsecond creation order.
        LeadInjection.objects.filter(pk=older.pk).update(
            created_at=LeadInjection.objects.get(pk=newer.pk).created_at.replace(year=2020))

        leads = [lead]
        attach_latest_injections(leads)
        assert leads[0].latest_injection.pk == newer.pk

    def test_lead_with_no_injection_gets_none(self, buyer):
        lead = _lead(buyer)
        leads = [lead]
        attach_latest_injections(leads)
        assert leads[0].latest_injection is None

    def test_one_query_regardless_of_lead_count(self, buyer, django_assert_num_queries):
        leads = [_lead(buyer, email=f'nq{i}@test.com') for i in range(5)]
        for lead in leads:
            LeadInjection.objects.create(lead=lead, buyer=buyer, status=LeadInjection.STATUS_DELIVERED)
        with django_assert_num_queries(1):
            attach_latest_injections(leads)
