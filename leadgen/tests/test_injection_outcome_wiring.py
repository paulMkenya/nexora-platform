"""The orchestrator half of the failure-classification contract.

connectors.py decides WHAT a failure means; inject_lead_task decides what
happens next. This file tests the seam — the part that is silent when wrong:

  * an ambiguous outcome must NOT retry and must NOT cascade (double-sell),
  * a clean reject must cascade immediately without burning the retry budget,
  * a genuinely retryable failure must still retry the SAME buyer,
  * the buyer's response must be sanitised before it is persisted.

The handler order in inject_lead_task is load-bearing: both new exception
types subclass LeadBuyerError, so testing the base first would collapse all
three branches into "retry". Every test here would pass with the guards
present and fail with them wired in the wrong order.
"""
from unittest.mock import MagicMock, patch

import pytest

from leadgen.connectors import (
    LeadBuyerAmbiguousError, LeadBuyerError, LeadBuyerRejectedError,
)
from leadgen.models import Lead, LeadInjection
from leadgen.tasks import inject_lead_task


@pytest.fixture
def lead(db, brand):
    return Lead.objects.create(
        brand=brand, intake_channel=Lead.CHANNEL_LANDING_PAGE,
        email='outcome@test.com', phone='+15551230000',
    )


@pytest.fixture
def injection(db, lead, buyer):
    return LeadInjection.objects.create(lead=lead, buyer=buyer)


def _run_with(injection, *, side_effect=None, response=None):
    """Drive inject_lead_task with a stubbed connector call."""
    connector = MagicMock()
    connector.build_payload.return_value = {'email': 'outcome@test.com'}
    connector.sanitize_response_for_audit.side_effect = lambda r: r
    if side_effect is not None:
        connector.inject_lead.side_effect = side_effect
    else:
        connector.inject_lead.return_value = response
        connector.parse_injection_result.return_value = ('ext-1', 'delivered', '')
    with patch('leadgen.connectors.get_connector', return_value=connector):
        try:
            inject_lead_task(injection.pk)
        except Exception:
            # A scheduled Celery retry raises Retry — the row state is what
            # this file asserts on, not the exception.
            pass
    injection.refresh_from_db()
    injection.lead.refresh_from_db()
    return connector


@pytest.mark.django_db
class TestAmbiguousOutcome:
    """THE double-sell guard. Before this wiring an unparseable 200 was
    retried three times and then handed to the next buyer — even though the
    first buyer may have created the lead."""

    def test_quarantines_the_lead(self, injection):
        _run_with(injection, side_effect=LeadBuyerAmbiguousError('outcome unknown'))
        assert injection.lead.status == Lead.STATUS_QUARANTINED

    def test_does_not_schedule_a_retry(self, injection):
        _run_with(injection, side_effect=LeadBuyerAmbiguousError('outcome unknown'))
        assert injection.next_retry_at is None
        assert injection.attempts == 1

    def test_does_not_cascade_to_another_buyer(self, injection):
        """Cascading here is the double-sell. advance_chain must not run."""
        injection.chain_managed = True
        injection.save(update_fields=['chain_managed'])
        with patch('leadgen.failover.advance_chain') as advance:
            _run_with(injection, side_effect=LeadBuyerAmbiguousError('outcome unknown'))
        advance.assert_not_called()

    def test_records_the_reason_for_the_human_who_reviews_it(self, injection):
        _run_with(injection, side_effect=LeadBuyerAmbiguousError('read timeout after 15s'))
        assert 'read timeout' in injection.failure_reason


@pytest.mark.django_db
class TestRejectedOutcome:
    def test_marks_the_lead_rejected_without_retrying(self, injection):
        _run_with(injection, side_effect=LeadBuyerRejectedError('bad phone', status_code=400))
        assert injection.lead.status == Lead.STATUS_REJECTED
        assert injection.next_retry_at is None
        assert injection.attempts == 1

    def test_cascades_immediately_when_chain_managed(self, injection):
        injection.chain_managed = True
        injection.save(update_fields=['chain_managed'])
        with patch('leadgen.failover.advance_chain') as advance:
            _run_with(injection, side_effect=LeadBuyerRejectedError('nope', status_code=422))
        advance.assert_called_once_with(injection.lead_id)


@pytest.mark.django_db
class TestRetryableOutcome:
    """Unchanged behaviour — proving the new branches did not swallow it."""

    def test_still_schedules_a_retry_against_the_same_buyer(self, injection):
        _run_with(injection, side_effect=LeadBuyerError('503 unavailable', status_code=503))
        assert injection.next_retry_at is not None
        assert injection.status == LeadInjection.STATUS_PENDING

    def test_rate_limit_is_retried_not_cascaded(self, injection):
        """429 means "slow down", not "no". Cascading it would hand the lead
        to a competitor the intended buyer would have taken."""
        injection.chain_managed = True
        injection.save(update_fields=['chain_managed'])
        with patch('leadgen.failover.advance_chain') as advance:
            _run_with(injection, side_effect=LeadBuyerError('rate limited', status_code=429))
        advance.assert_not_called()
        assert injection.next_retry_at is not None


@pytest.mark.django_db
class TestResponseIsSanitisedBeforePersisting:
    def test_sanitize_is_applied_to_what_gets_stored(self, injection):
        """response_payload is affiliate- and operator-visible, so the raw
        buyer response must never be persisted verbatim."""
        connector = MagicMock()
        connector.build_payload.return_value = {}
        connector.inject_lead.return_value = {
            'success': True, 'leadId': 'x', 'redirectUrl': 'https://secret/'}
        connector.sanitize_response_for_audit.return_value = {
            'success': True, 'leadId': 'x', 'redirectUrl': '[redacted]'}
        connector.parse_injection_result.return_value = ('x', 'delivered', '')

        with patch('leadgen.connectors.get_connector', return_value=connector):
            inject_lead_task(injection.pk)
        injection.refresh_from_db()

        connector.sanitize_response_for_audit.assert_called_once()
        assert injection.response_payload['redirectUrl'] == '[redacted]'
        assert 'https://secret/' not in str(injection.response_payload)


@pytest.mark.django_db
class TestStatusSyncGate:
    def test_a_connector_without_status_sync_is_skipped_not_raised(self, buyer, lead):
        """Hypernet's connector raises NotImplementedError rather than answer
        wrongly. Without this gate that surfaced on every Beat tick."""
        from leadgen.tasks import sync_buyer_statuses_for_buyer

        LeadInjection.objects.create(
            lead=lead, buyer=buyer, status=LeadInjection.STATUS_DELIVERED, external_id='e1')

        connector = MagicMock()
        connector.supports_status_sync = False
        connector.fetch_lead_statuses.side_effect = NotImplementedError('no date-range sync')

        with patch('leadgen.connectors.get_connector', return_value=connector):
            assert sync_buyer_statuses_for_buyer(buyer) == 0
        connector.fetch_lead_statuses.assert_not_called()
