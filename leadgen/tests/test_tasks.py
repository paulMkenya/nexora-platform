"""Tests for leadgen/tasks.py — buyer resolution, the auto-inject
kill-switch, and inject_lead_task's success/duplicate/reject/retry/
exhausted-retry paths. HTTP mocked at leadgen.connectors.requests.request,
same as test_connectors.py."""
from unittest.mock import MagicMock, patch

import pytest
import requests

from leadgen.models import Lead, LeadBuyer, LeadInjection
from leadgen.tasks import inject_lead_task, maybe_auto_inject, resolve_buyer_for_lead


def _lead(**kwargs):
    defaults = dict(intake_channel=Lead.CHANNEL_LANDING_PAGE, email='jane@test.com', phone='+15551234567')
    defaults.update(kwargs)
    return Lead.objects.create(**defaults)


@pytest.mark.django_db
class TestResolveBuyerForLead:
    def test_brand_scoped_buyer_preferred_over_platform_wide(self, brand, buyer):
        brand_buyer = LeadBuyer.objects.create(
            brand=brand, name='Brand Buyer', slug='brand-buyer', is_active=True,
            base_url='https://brandbuyer.test',
        )
        lead = _lead(brand=brand)
        assert resolve_buyer_for_lead(lead) == brand_buyer

    def test_falls_back_to_platform_wide_buyer(self, brand, buyer):
        lead = _lead(brand=brand)  # no brand-scoped buyer configured
        assert resolve_buyer_for_lead(lead) == buyer

    def test_inactive_buyer_is_not_resolved(self, buyer):
        buyer.is_active = False
        buyer.save(update_fields=['is_active'])
        lead = _lead()
        assert resolve_buyer_for_lead(lead) is None

    def test_no_buyer_configured_returns_none(self, db):
        lead = _lead()
        assert resolve_buyer_for_lead(lead) is None


@pytest.mark.django_db
class TestMaybeAutoInject:
    def test_no_buyer_does_not_enqueue(self, db):
        lead = _lead()
        assert maybe_auto_inject(lead) is None
        assert LeadInjection.objects.count() == 0

    def test_buyer_with_auto_inject_off_does_not_enqueue(self, buyer):
        assert buyer.auto_inject is False
        lead = _lead()
        assert maybe_auto_inject(lead) is None
        assert LeadInjection.objects.count() == 0

    def test_buyer_with_auto_inject_on_enqueues(self, buyer):
        buyer.auto_inject = True
        buyer.save(update_fields=['auto_inject'])
        lead = _lead()
        with patch('leadgen.tasks.inject_lead_task.delay') as mock_delay:
            injection = maybe_auto_inject(lead)
        assert injection is not None
        assert injection.status == LeadInjection.STATUS_PENDING
        mock_delay.assert_called_once_with(injection.pk)


@pytest.mark.django_db
class TestInjectLeadTask:
    def test_successful_delivery_marks_injection_and_lead(self, buyer):
        lead = _lead()
        injection = LeadInjection.objects.create(lead=lead, buyer=buyer)
        mock_resp = MagicMock(ok=True, content=b'{}',
                               json=lambda: {'addedLeads': [{'id': 'ext-1'}], 'failedToAddLeads': []})
        with patch('leadgen.connectors.requests.request', return_value=mock_resp):
            inject_lead_task(injection.pk)

        injection.refresh_from_db()
        lead.refresh_from_db()
        assert injection.status == LeadInjection.STATUS_DELIVERED
        assert injection.external_id == 'ext-1'
        assert injection.attempts == 1
        assert injection.delivered_at is not None
        assert lead.status == Lead.STATUS_INJECTED

    def test_duplicate_response_marks_duplicate(self, buyer):
        lead = _lead()
        injection = LeadInjection.objects.create(lead=lead, buyer=buyer)
        mock_resp = MagicMock(ok=True, content=b'{}', json=lambda: {
            'addedLeads': [],
            'failedToAddLeads': [{'failureReason': 'duplicate', 'failureMessages': ['dup']}],
        })
        with patch('leadgen.connectors.requests.request', return_value=mock_resp):
            inject_lead_task(injection.pk)

        injection.refresh_from_db()
        lead.refresh_from_db()
        assert injection.status == LeadInjection.STATUS_DUPLICATE
        assert lead.status == Lead.STATUS_DUPLICATE

    def test_buyer_rejection_is_terminal_not_retried(self, buyer):
        lead = _lead()
        injection = LeadInjection.objects.create(lead=lead, buyer=buyer)
        mock_resp = MagicMock(ok=True, content=b'{}', json=lambda: {
            'addedLeads': [],
            'failedToAddLeads': [{'failureReason': 'invalid_phone', 'failureMessages': ['bad phone']}],
        })
        with patch('leadgen.connectors.requests.request', return_value=mock_resp):
            inject_lead_task(injection.pk)

        injection.refresh_from_db()
        lead.refresh_from_db()
        assert injection.status == LeadInjection.STATUS_FAILED
        assert injection.attempts == 1  # no retry attempted
        assert lead.status == Lead.STATUS_REJECTED

    def test_transport_error_schedules_retry_with_backoff(self, buyer):
        lead = _lead()
        injection = LeadInjection.objects.create(lead=lead, buyer=buyer)
        with patch('leadgen.connectors.requests.request',
                   side_effect=requests.ConnectionError('connection refused')):
            try:
                inject_lead_task(injection.pk)
            except Exception:
                pass  # Celery's self.retry() raises Retry outside a real worker

        injection.refresh_from_db()
        assert injection.attempts == 1
        assert injection.status == LeadInjection.STATUS_PENDING  # not yet terminal
        assert injection.next_retry_at is not None

    def test_exhausted_retries_marks_failed(self, buyer):
        lead = _lead()
        injection = LeadInjection.objects.create(
            lead=lead, buyer=buyer, attempts=len(LeadInjection.RETRY_BACKOFFS) - 1)
        with patch('leadgen.connectors.requests.request', side_effect=requests.ConnectionError('still down')):
            try:
                inject_lead_task(injection.pk)
            except Exception:
                pass

        injection.refresh_from_db()
        lead.refresh_from_db()
        assert injection.attempts == len(LeadInjection.RETRY_BACKOFFS)
        assert injection.status == LeadInjection.STATUS_FAILED
        assert lead.status == Lead.STATUS_FAILED

    def test_already_delivered_injection_is_not_resent(self, buyer):
        lead = _lead()
        injection = LeadInjection.objects.create(lead=lead, buyer=buyer, status=LeadInjection.STATUS_DELIVERED)
        with patch('leadgen.connectors.requests.request') as mock_req:
            inject_lead_task(injection.pk)
        mock_req.assert_not_called()

    def test_missing_injection_is_a_noop(self, db):
        with patch('leadgen.connectors.requests.request') as mock_req:
            inject_lead_task(999999)
        mock_req.assert_not_called()

    def test_request_payload_never_contains_api_key(self, buyer):
        lead = _lead()
        injection = LeadInjection.objects.create(lead=lead, buyer=buyer)
        mock_resp = MagicMock(ok=True, content=b'{}', json=lambda: {'addedLeads': [{'id': '1'}]})
        with patch('leadgen.connectors.requests.request', return_value=mock_resp):
            inject_lead_task(injection.pk)

        injection.refresh_from_db()
        assert 'raw-test-secret' not in str(injection.request_payload)
        assert 'raw-test-secret' not in str(injection.response_payload)
