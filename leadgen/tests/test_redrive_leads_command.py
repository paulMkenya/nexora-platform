"""Tests for the redrive_leads management command.

The command exists because of a real loss: a capacity refusal recorded as a
rejection is terminal, and nothing on the platform re-drives a rejected lead
(inject_pending_leads only looks at STATUS_NEW). What is pinned here is
mostly the SAFETY half — a recovery tool that re-sends an already-sold lead
does more damage than the bug it is cleaning up after.
"""
from io import StringIO
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from leadgen.models import Lead, LeadInjection


def _lead(buyer, status=Lead.STATUS_REJECTED, **kwargs):
    defaults = dict(
        intake_channel=Lead.CHANNEL_LANDING_PAGE, email='redrive@test.com',
        phone='+15551234567', brand=buyer.brand, status=status,
    )
    defaults.update(kwargs)
    return Lead.objects.create(**defaults)


def _failed(lead, buyer, reason='No hubs available for this lead.'):
    return LeadInjection.objects.create(
        lead=lead, buyer=buyer, status=LeadInjection.STATUS_FAILED, failure_reason=reason)


@pytest.mark.django_db
class TestRedriveLeadsCommand:
    def test_a_rejected_lead_is_re_enqueued_by_id(self, buyer):
        lead = _lead(buyer)
        _failed(lead, buyer)
        with patch('leadgen.services.inject_lead_task') as mock_task:
            call_command('redrive_leads', ids=str(lead.pk), stdout=StringIO())
        assert LeadInjection.objects.filter(lead=lead).count() == 2
        mock_task.delay.assert_called_once()
        mock_task.assert_not_called()  # queued, never run inline

    def test_selection_by_what_the_buyer_said(self, buyer):
        wanted = _lead(buyer, email='hubs@test.com')
        _failed(wanted, buyer, 'No hubs available for this lead.')
        other = _lead(buyer, email='phone@test.com')
        _failed(other, buyer, 'Invalid phone number')

        with patch('leadgen.services.inject_lead_task'):
            call_command('redrive_leads', reason_contains='no hubs available', stdout=StringIO())

        assert LeadInjection.objects.filter(lead=wanted).count() == 2
        assert LeadInjection.objects.filter(lead=other).count() == 1

    def test_a_delivered_lead_is_never_re_sent(self, buyer):
        """A lead is sold once. This is the failure mode that would make the
        recovery worse than the incident."""
        lead = _lead(buyer, status=Lead.STATUS_INJECTED)
        LeadInjection.objects.create(
            lead=lead, buyer=buyer, status=LeadInjection.STATUS_DELIVERED)
        out = StringIO()
        with patch('leadgen.services.inject_lead_task') as mock_task:
            call_command('redrive_leads', ids=str(lead.pk), stdout=out)
        mock_task.delay.assert_not_called()
        assert 'already delivered' in out.getvalue()

    def test_a_lead_still_in_flight_is_left_alone(self, buyer):
        """Its retry schedule is already running; a second injection would
        race it and could double-deliver."""
        lead = _lead(buyer)
        LeadInjection.objects.create(lead=lead, buyer=buyer, status=LeadInjection.STATUS_PENDING)
        out = StringIO()
        with patch('leadgen.services.inject_lead_task') as mock_task:
            call_command('redrive_leads', ids=str(lead.pk), stdout=out)
        mock_task.delay.assert_not_called()
        assert 'still in flight' in out.getvalue()

    def test_dry_run_changes_nothing(self, buyer):
        lead = _lead(buyer)
        _failed(lead, buyer)
        out = StringIO()
        with patch('leadgen.services.inject_lead_task') as mock_task:
            call_command('redrive_leads', ids=str(lead.pk), dry_run=True, stdout=out)
        assert LeadInjection.objects.filter(lead=lead).count() == 1
        mock_task.delay.assert_not_called()
        assert 'would re-drive' in out.getvalue().lower()

    def test_no_selector_is_refused(self, buyer):
        with pytest.raises(CommandError):
            call_command('redrive_leads', stdout=StringIO())

    def test_an_unknown_buyer_slug_is_refused(self, buyer):
        lead = _lead(buyer)
        _failed(lead, buyer)
        with pytest.raises(CommandError):
            call_command('redrive_leads', ids=str(lead.pk), buyer='nope', stdout=StringIO())


@pytest.mark.django_db
class TestTheStaleVerdictIsCleared:
    """A re-driven lead must stop claiming a verdict no buyer stands behind.

    inject_lead_task writes Lead.status only when it reaches an outcome, so
    without this the lead reads `rejected` for the entire retry window — up to
    ~11h on CAPACITY_RETRY_BACKOFFS — while an injection is actively in
    flight. That status is what the affiliate API returns.
    """

    def test_a_re_driven_lead_goes_back_to_new(self, buyer):
        lead = _lead(buyer, status=Lead.STATUS_REJECTED)
        _failed(lead, buyer)
        with patch('leadgen.services.inject_lead_task'):
            call_command('redrive_leads', ids=str(lead.pk), stdout=StringIO())
        lead.refresh_from_db()
        assert lead.status == Lead.STATUS_NEW

    def test_a_dry_run_changes_nothing(self, buyer):
        lead = _lead(buyer, status=Lead.STATUS_REJECTED)
        _failed(lead, buyer)
        with patch('leadgen.services.inject_lead_task'):
            call_command('redrive_leads', ids=str(lead.pk), dry_run=True, stdout=StringIO())
        lead.refresh_from_db()
        assert lead.status == Lead.STATUS_REJECTED

    def test_a_skipped_lead_keeps_its_status(self, buyer):
        """A lead already delivered is skipped — and must NOT be walked back
        to `new`, which would erase a real sale from every report built on
        lead status."""
        lead = _lead(buyer, status=Lead.STATUS_INJECTED)
        LeadInjection.objects.create(
            lead=lead, buyer=buyer, status=LeadInjection.STATUS_DELIVERED)
        with patch('leadgen.services.inject_lead_task'):
            call_command('redrive_leads', ids=str(lead.pk), stdout=StringIO())
        lead.refresh_from_db()
        assert lead.status == Lead.STATUS_INJECTED
