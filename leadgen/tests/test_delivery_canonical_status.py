"""canonical_status must describe a lead's whole life, not just the part a
buyer witnessed.

WHAT WENT WRONG. canonical_status was written only by a buyer report or an
operator flip, so a lead that never reached a buyer read as '' forever. That
empty string meant two opposite things — "just arrived, nothing has happened"
and "refused five times, nobody is coming" — and the affiliate doc points
sources at exactly this field. Lead 98 surfaced it: capacity-refused at
Badboys, retried to exhaustion, still reported as blank.

THE INVARIANT THIS FILE DEFENDS: the buyer outranks the delivery layer,
always. Once a buyer-sourced event has APPLIED, nothing in delivery_status
writes again — otherwise a redrive resetting Lead.status to `new` would
overwrite the buyer's verdict on a real person with 'new'.
"""
import pytest

from leadgen import canonical_status, delivery_status
from leadgen.models import AffiliateOfferLink, Lead, LeadStatusEvent
from leadgen.status_sync import apply_status_change


@pytest.fixture
def lead(db, brand):
    return Lead.objects.create(
        brand=brand, first_name='A', last_name='B',
        email='a@b.test', phone='+447700900123', country_iso2='PL',
    )


@pytest.mark.django_db
class TestEveryDeliveryStateIsReportable:
    @pytest.mark.parametrize('delivery,expected', [
        (Lead.STATUS_NEW, canonical_status.NEW),
        (Lead.STATUS_INJECTED, canonical_status.ROUTED),
        (Lead.STATUS_DUPLICATE, canonical_status.DUPLICATE),
        (Lead.STATUS_REJECTED, canonical_status.REJECTED),
        (Lead.STATUS_FAILED, canonical_status.FAILED),
        (Lead.STATUS_UNROUTED, canonical_status.UNROUTED),
    ])
    def test_it_reports(self, lead, delivery, expected):
        Lead.objects.filter(pk=lead.pk).update(status=delivery)
        delivery_status.report(lead.pk)
        lead.refresh_from_db()
        assert lead.canonical_status == expected

    def test_the_capacity_exhausted_case_that_prompted_this(self, lead):
        """Lead 98's exact shape: refused by the buyer until its retries ran
        out. `failed` is the honest answer and '' was not."""
        Lead.objects.filter(pk=lead.pk).update(status=Lead.STATUS_FAILED)
        delivery_status.report(lead.pk)
        lead.refresh_from_db()
        assert lead.canonical_status == canonical_status.FAILED

    def test_quarantined_asserts_nothing(self, lead):
        """An ambiguous outcome means we do not KNOW whether the buyer took
        the lead. Reporting `failed` would assert an outcome nobody observed
        and may be flatly untrue — the lead can be live in the buyer's CRM."""
        Lead.objects.filter(pk=lead.pk).update(
            status=Lead.STATUS_NEW, canonical_status=canonical_status.NEW)
        Lead.objects.filter(pk=lead.pk).update(status=Lead.STATUS_QUARANTINED)
        delivery_status.report(lead.pk)
        lead.refresh_from_db()
        assert lead.canonical_status == canonical_status.NEW

    def test_it_writes_an_auditable_system_event(self, lead):
        Lead.objects.filter(pk=lead.pk).update(status=Lead.STATUS_UNROUTED)
        delivery_status.report(lead.pk)
        event = lead.status_events.get()
        assert event.source == LeadStatusEvent.SOURCE_SYSTEM
        assert event.to_status == canonical_status.UNROUTED
        assert event.applied is True

    def test_repeating_it_writes_nothing_new(self, lead):
        Lead.objects.filter(pk=lead.pk).update(status=Lead.STATUS_FAILED)
        for _ in range(3):
            delivery_status.report(lead.pk)
        assert lead.status_events.count() == 1

    def test_a_missing_lead_is_not_an_error(self, db):
        assert delivery_status.report(999999) is None


@pytest.mark.django_db
class TestTheBuyerOutranksUs:
    @pytest.fixture
    def lead_the_buyer_has_judged(self, lead, affiliate_user, offer):
        lead.affiliate = affiliate_user
        lead.offer = offer
        lead.save(update_fields=['affiliate', 'offer'])
        AffiliateOfferLink.objects.update_or_create(
            affiliate=affiliate_user, offer=offer,
            defaults={'phase': AffiliateOfferLink.PHASE_LIVE})
        apply_status_change(lead, canonical_status.NO_ANSWER,
                            source=LeadStatusEvent.SOURCE_BUYER)
        lead.refresh_from_db()
        assert lead.canonical_status == canonical_status.NO_ANSWER
        return lead

    def test_a_redrive_cannot_reset_the_buyers_verdict(self, lead_the_buyer_has_judged):
        """THE REGRESSION THIS GUARDS. redrive_leads sets Lead.status back to
        `new`. Without the guard that would report canonical `new` over the
        buyer's `no_answer` — losing a real verdict about a real person, and
        firing nothing to say it happened."""
        lead = lead_the_buyer_has_judged
        Lead.objects.filter(pk=lead.pk).update(status=Lead.STATUS_NEW)
        delivery_status.report(lead.pk)
        lead.refresh_from_db()
        assert lead.canonical_status == canonical_status.NO_ANSWER

    def test_nor_can_a_later_delivery_failure(self, lead_the_buyer_has_judged):
        lead = lead_the_buyer_has_judged
        Lead.objects.filter(pk=lead.pk).update(status=Lead.STATUS_FAILED)
        delivery_status.report(lead.pk)
        lead.refresh_from_db()
        assert lead.canonical_status == canonical_status.NO_ANSWER

    def test_an_unapplied_testing_report_does_NOT_lock_us_out(self, lead, affiliate_user, offer):
        """A TESTING-phase buyer report is recorded but never applied, so it
        is not the buyer's word on canonical_status yet. Treating it as such
        would freeze every testing-phase lead at blank — the opposite of the
        bug being fixed."""
        lead.affiliate = affiliate_user
        lead.offer = offer
        lead.save(update_fields=['affiliate', 'offer'])
        AffiliateOfferLink.objects.update_or_create(
            affiliate=affiliate_user, offer=offer,
            defaults={'phase': AffiliateOfferLink.PHASE_TESTING})
        apply_status_change(lead, canonical_status.NO_ANSWER,
                            source=LeadStatusEvent.SOURCE_BUYER)
        lead.refresh_from_db()
        assert lead.canonical_status == ''

        Lead.objects.filter(pk=lead.pk).update(status=Lead.STATUS_FAILED)
        delivery_status.report(lead.pk)
        lead.refresh_from_db()
        assert lead.canonical_status == canonical_status.FAILED


@pytest.mark.django_db
class TestPostbackNoise:
    """An affiliate is woken for outcomes they can act on, not for progress."""

    @pytest.mark.parametrize('delivery', [Lead.STATUS_NEW, Lead.STATUS_INJECTED])
    def test_progress_does_not_fire_a_postback(self, lead, delivery, monkeypatch):
        fired = []
        monkeypatch.setattr('leadgen.postback_delivery.dispatch_postbacks_for_event',
                            lambda event: fired.append(event))
        Lead.objects.filter(pk=lead.pk).update(status=delivery)
        delivery_status.report(lead.pk)
        assert fired == []

    @pytest.mark.parametrize('delivery', [
        Lead.STATUS_FAILED, Lead.STATUS_REJECTED,
        Lead.STATUS_UNROUTED, Lead.STATUS_DUPLICATE,
    ])
    def test_a_terminal_failure_does(self, lead, delivery, monkeypatch):
        fired = []
        monkeypatch.setattr('leadgen.postback_delivery.dispatch_postbacks_for_event',
                            lambda event: fired.append(event))
        Lead.objects.filter(pk=lead.pk).update(status=delivery)
        delivery_status.report(lead.pk)
        assert len(fired) == 1

    def test_a_buyer_report_still_notifies_exactly_as_before(self, lead, monkeypatch):
        """The notify parameter defaults True; no existing caller changed."""
        fired = []
        monkeypatch.setattr('leadgen.postback_delivery.dispatch_postbacks_for_event',
                            lambda event: fired.append(event))
        apply_status_change(lead, canonical_status.FTD, source=LeadStatusEvent.SOURCE_BUYER)
        assert len(fired) == 1


@pytest.mark.django_db
class TestReportingNeverBreaksDelivery:
    def test_an_internal_failure_is_swallowed_and_logged(self, lead, monkeypatch, caplog):
        """Every call site is on a live injection path. A reporting bug must
        never fail a delivery — or worse, raise into a Celery task and cause a
        retry that sends the same lead to the buyer twice."""
        def boom(*a, **kw):
            raise RuntimeError('reporting is broken')

        monkeypatch.setattr('leadgen.delivery_status.apply_status_change', boom)
        Lead.objects.filter(pk=lead.pk).update(status=Lead.STATUS_FAILED)
        assert delivery_status.report(lead.pk) is None
        assert 'delivery_status.report failed' in caplog.text
