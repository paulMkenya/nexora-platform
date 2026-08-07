"""The sweep that makes a retry schedule survive a worker restart.

A retry lives in the worker's MEMORY: self.retry() hands the task back to
the broker with an ETA and the worker holds it until it fires. Restart the
worker and every pending retry is gone — silently, with next_retry_at still
reading like a promise. Deploying 2b6913f on 2026-08-07 dropped all 31
in-flight ChainPulse retries exactly that way; the rows looked healthy
afterwards and not one of those leads would have been sent again.

What is actually worth pinning here is not "it dispatches things" but the
three judgements that keep it from doing harm:

  * it must NOT touch a retry Celery still holds (that is a double-send to
    a paying buyer, the failure this codebase treats most seriously);
  * two overlapping sweeps must not both dispatch the same row;
  * a claim whose dispatch is then lost must not become a permanent orphan
    — which is the very thing the sweep exists to prevent, and the easiest
    way to reintroduce it is a one-shot claim that clears next_retry_at.

No network: nothing here lets the task reach a buyer.
"""
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from leadgen.models import Lead, LeadInjection
from leadgen.tasks import (
    SWEEP_GRACE, SWEEP_RECLAIM_AFTER, sweep_due_injections,
)


@pytest.fixture
def lead(db, brand):
    return Lead.objects.create(
        brand=brand, intake_channel=Lead.CHANNEL_AFFILIATE_API,
        email='sweep@test.com', phone='+5545988343630')


def _injection(lead, buyer, *, status=LeadInjection.STATUS_PENDING, due_ago=None,
               due_in=None, attempts=1):
    """An injection whose next_retry_at is `due_ago` in the past (or `due_in`
    in the future, or absent)."""
    next_retry_at = None
    if due_ago is not None:
        next_retry_at = timezone.now() - due_ago
    elif due_in is not None:
        next_retry_at = timezone.now() + due_in
    return LeadInjection.objects.create(
        lead=lead, buyer=buyer, status=status, attempts=attempts,
        next_retry_at=next_retry_at)


@pytest.mark.django_db
class TestWhatItPicksUp:

    def test_an_orphaned_retry_is_redispatched(self, lead, buyer):
        injection = _injection(lead, buyer, due_ago=SWEEP_GRACE + timedelta(minutes=1))
        with patch('leadgen.tasks.inject_lead_task.delay') as dispatch:
            assert sweep_due_injections() == 1
        dispatch.assert_called_once_with(injection.pk)

    def test_a_retry_celery_may_still_hold_is_left_alone(self, lead, buyer):
        """Inside the grace margin, a due-but-not-yet-run retry is the NORMAL
        state — the worker is about to fire it. Dispatching here would send
        the lead to the buyer twice."""
        injection = _injection(lead, buyer, due_ago=timedelta(seconds=30))
        with patch('leadgen.tasks.inject_lead_task.delay') as dispatch:
            assert sweep_due_injections() == 0
        dispatch.assert_not_called()
        injection.refresh_from_db()
        assert injection.next_retry_at is not None, 'claimed a row it did not dispatch'

    def test_a_future_retry_is_left_alone(self, lead, buyer):
        _injection(lead, buyer, due_in=timedelta(hours=3))
        with patch('leadgen.tasks.inject_lead_task.delay') as dispatch:
            assert sweep_due_injections() == 0
        dispatch.assert_not_called()

    @pytest.mark.parametrize('status', [
        LeadInjection.STATUS_DELIVERED,
        LeadInjection.STATUS_FAILED,
        LeadInjection.STATUS_DUPLICATE,
    ])
    def test_a_settled_injection_is_never_resurrected(self, lead, buyer, status):
        """The terminal branches do not CLEAR next_retry_at, so a settled row
        can carry a stale one indefinitely. Sweeping on the timestamp alone
        would re-send leads the buyer already took, or already refused."""
        _injection(lead, buyer, status=status, due_ago=timedelta(hours=6))
        with patch('leadgen.tasks.inject_lead_task.delay') as dispatch:
            assert sweep_due_injections() == 0
        dispatch.assert_not_called()

    def test_an_injection_with_no_retry_time_is_ignored(self, lead, buyer):
        """Pending with no next_retry_at means nothing ever asked for a
        retry — a brand-new row, not an orphan."""
        _injection(lead, buyer)
        with patch('leadgen.tasks.inject_lead_task.delay') as dispatch:
            assert sweep_due_injections() == 0
        dispatch.assert_not_called()

    def test_the_batch_is_bounded(self, lead, buyer):
        for _ in range(5):
            _injection(lead, buyer, due_ago=SWEEP_GRACE + timedelta(minutes=1))
        with patch('leadgen.tasks.inject_lead_task.delay') as dispatch:
            assert sweep_due_injections(limit=2) == 2
        assert dispatch.call_count == 2


@pytest.mark.django_db
class TestTheClaim:
    """Claiming is what stops one orphan becoming two deliveries."""

    def test_claiming_pushes_the_retry_time_forward_rather_than_clearing_it(
            self, lead, buyer):
        """A one-shot claim (next_retry_at = None) would mean a dispatch lost
        between claim and enqueue leaves the row with no due time at all —
        permanently orphaned, by the fix for permanent orphans. Pushing it
        forward makes a lost dispatch simply come due again."""
        injection = _injection(lead, buyer, due_ago=SWEEP_GRACE + timedelta(minutes=1))
        before = timezone.now()
        with patch('leadgen.tasks.inject_lead_task.delay'):
            sweep_due_injections()

        injection.refresh_from_db()
        assert injection.next_retry_at is not None
        assert injection.next_retry_at > before + SWEEP_RECLAIM_AFTER - timedelta(seconds=30)

    def test_a_claimed_row_is_not_swept_again_immediately(self, lead, buyer):
        """The second sweep a minute later must not re-dispatch what the
        first one just handed to Celery."""
        _injection(lead, buyer, due_ago=SWEEP_GRACE + timedelta(minutes=1))
        with patch('leadgen.tasks.inject_lead_task.delay') as dispatch:
            assert sweep_due_injections() == 1
            assert sweep_due_injections() == 0
        assert dispatch.call_count == 1

    def test_a_row_that_changed_under_us_is_not_dispatched(self, lead, buyer):
        """Compare-and-set: if anything moved next_retry_at between the read
        and the claim — a concurrent sweep, or the real task rescheduling
        itself — this sweep must lose the race and dispatch nothing."""
        injection = _injection(lead, buyer, due_ago=SWEEP_GRACE + timedelta(minutes=1))

        real_filter = LeadInjection.objects.filter

        def steal_then_filter(*args, **kwargs):
            # Move the row the instant the sweep tries to claim it.
            if kwargs.get('pk') == injection.pk:
                real_filter(pk=injection.pk).update(
                    next_retry_at=timezone.now() + timedelta(hours=1))
            return real_filter(*args, **kwargs)

        with patch('leadgen.tasks.inject_lead_task.delay') as dispatch, \
             patch.object(LeadInjection.objects, 'filter', side_effect=steal_then_filter):
            assert sweep_due_injections() == 0
        dispatch.assert_not_called()


@pytest.mark.django_db
class TestItIsWiredUp:

    def test_it_is_on_the_beat_schedule(self):
        from project._celery import _celery

        scheduled = {
            cfg['task'] for cfg in (_celery.conf.beat_schedule or {}).values()}
        assert 'leadgen.tasks.sweep_due_injections' in scheduled, (
            'the sweep only protects anything if Beat actually runs it')

    def test_it_runs_often_enough_to_matter(self):
        from project._celery import _celery

        entry = _celery.conf.beat_schedule['sweep-due-lead-injections']
        assert entry['schedule'] <= 300, (
            'recovery latency after a restart is bounded by this interval')

    def test_a_healthy_sweep_is_silent_and_cheap(self, lead, buyer):
        """The steady state: nothing due, nothing dispatched, no writes."""
        _injection(lead, buyer, due_in=timedelta(hours=2))
        with patch('leadgen.tasks.inject_lead_task.delay') as dispatch:
            assert sweep_due_injections() == 0
        dispatch.assert_not_called()
