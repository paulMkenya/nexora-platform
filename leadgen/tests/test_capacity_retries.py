"""A buyer with no room is not a buyer saying no.

This file pins the LeadBuyerCapacityError path end to end: the detection
(which 4xx bodies earn it), the classification (which exception, and its
place in the hierarchy), and the handling (retry on the long schedule, or
cascade if there is anywhere to cascade to).

Why it earns its own file rather than a few cases bolted onto
test_error_classification.py: that file pins a table where every row is a
property of the HTTP status code alone. This path is the one place the
BODY decides the outcome, it is opt-in per connector, and its failure mode
is invisible — a lead classified wrong here does not raise, it just quietly
stops existing. On 2026-08-07 that cost ChainPulse 10 real Brazilian leads
in 40 minutes, each answered `[404] {"error": "No hubs available for this
lead."}` an hour after the same box accepted a byte-identical payload.

No network anywhere: requests.request is mocked, same pattern as
test_connectors.py and test_hypernet_connector.py.
"""
from unittest.mock import MagicMock, patch

import pytest

from leadgen.connectors import (
    HypernetConnector, LeadBuyerCapacityError, LeadBuyerConnector, LeadBuyerError,
    LeadBuyerRejectedError, get_connector,
)
from leadgen.models import BoxType, Lead, LeadBuyer, LeadInjection

# The exact envelope desperados answers when its router has no open hub.
NO_HUBS_BODY = {
    'success': False,
    'redirectUrl': None,
    'leadId': None,
    'error': 'No hubs available for this lead.',
}


@pytest.fixture
def hypernet_buyer(db, brand):
    """A buyer whose BoxType actually resolves to HypernetConnector.

    Built here rather than imported from test_hypernet_connector: the task
    tests below go through get_connector(), which picks the class from
    box_type.connector_class, so the wiring has to be real. Deliberately
    minimal — no affc/bxc/vtc, because nothing in this file asserts on the
    payload, only on how a FAILURE is classified.
    """
    box_type = BoxType.objects.create(
        name='Hypernet (capacity test)', slug='hypernet-capacity-test',
        connector_class='leadgen.connectors.HypernetConnector',
        auth_type=BoxType.AUTH_API_KEY_HEADER, auth_param_name='x-api-key',
        single_endpoint_path='/api/external/integration/lead',
        batch_endpoint_path='', fetch_endpoint_path='/api/external/integration/lead',
        batch_max_size=1,
        rate_limit_burst=10, rate_limit_refill_tokens=1, rate_limit_refill_seconds=1,
    )
    buyer = LeadBuyer.objects.create(
        brand=brand, box_type=box_type,
        name='Hypernet - desperados (test)', slug='hypernet-desperados-captest',
        is_active=True, auto_inject=False, base_url='https://desperados.hn-crm.com',
    )
    buyer.set_api_key('fake-test-key-not-the-real-one')
    buyer.save(update_fields=['api_key_encrypted'])
    return buyer


def _response(status_code, body):
    """A requests.Response stand-in whose .json() behaves like the real one:
    returns the parsed body, or raises ValueError when it isn't JSON."""
    resp = MagicMock(ok=False, status_code=status_code)
    resp.text = str(body)
    if body is None:
        resp.json.side_effect = ValueError('not JSON')
    else:
        resp.json.return_value = body
    return resp


def _inject(buyer, response, lead=None):
    """Drive a real inject_lead() into `response` and return what it raised."""
    connector = get_connector(buyer)
    lead = lead or Lead(intake_channel=Lead.CHANNEL_LANDING_PAGE,
                        email='jane@test.com', phone='+5545988343630')
    with patch('leadgen.connectors.requests.request', return_value=response):
        with pytest.raises(LeadBuyerError) as exc_info:
            connector.inject_lead(lead)
    return exc_info.value


@pytest.mark.django_db
class TestDetection:
    """Which failures count as "no capacity" — and, more importantly, which
    do not. Every False here would otherwise become an hours-long retry on a
    lead that will never be accepted."""

    def test_no_hubs_available_is_a_capacity_error(self, hypernet_buyer):
        exc = _inject(hypernet_buyer, _response(404, NO_HUBS_BODY))
        assert isinstance(exc, LeadBuyerCapacityError)
        assert exc.status_code == 404

    @pytest.mark.parametrize('message', [
        'No hubs available for this lead.',
        'no hubs available',
        'No Hubs Available',
        'No  hub  available',                      # spacing/plural drift
        'No hubs available for this lead (geo: BR).',   # suffixed
    ])
    def test_wording_drift_within_reason_still_matches(self, hypernet_buyer, message):
        exc = _inject(hypernet_buyer, _response(404, {**NO_HUBS_BODY, 'error': message}))
        assert isinstance(exc, LeadBuyerCapacityError)

    def test_a_404_without_that_message_is_still_a_rejection(self, hypernet_buyer):
        """The status code alone must never be enough. A bare 404 is also
        what a wrong single_endpoint_path returns, and retrying THAT for ten
        hours would bury a misconfiguration instead of surfacing it."""
        exc = _inject(hypernet_buyer, _response(404, {'message': 'Not Found'}))
        assert isinstance(exc, LeadBuyerRejectedError)
        assert not isinstance(exc, LeadBuyerCapacityError)

    def test_their_validation_400_is_still_a_rejection(self, hypernet_buyer):
        """Real body from the live box on lead 26 — a payload verdict, which
        no amount of waiting improves."""
        exc = _inject(hypernet_buyer, _response(400, {
            'message': 'Validation error. ("funnel" is required)',
            'code': 'vldE', 'statusCode': 400,
        }))
        assert isinstance(exc, LeadBuyerRejectedError)
        assert not isinstance(exc, LeadBuyerCapacityError)

    def test_a_non_json_404_is_a_rejection(self, hypernet_buyer):
        """Some proxy or WAF answering instead of the box says nothing about
        the box's capacity."""
        exc = _inject(hypernet_buyer, _response(404, None))
        assert isinstance(exc, LeadBuyerRejectedError)

    def test_the_base_connector_never_claims_capacity(self, buyer):
        """Default-deny: the identical body against a buyer whose connector
        has not opted in keeps today's exact behaviour."""
        exc = _inject(buyer, _response(404, NO_HUBS_BODY))
        assert isinstance(exc, LeadBuyerRejectedError)
        assert not isinstance(exc, LeadBuyerCapacityError)

    def test_an_override_that_raises_degrades_to_rejection(self, buyer):
        """The classifier must not be able to crash. An override throwing on
        an unexpected body would otherwise replace a clean rejection with an
        unhandled exception, on the one code path whose job is to classify
        failures."""
        with patch.object(LeadBuyerConnector, 'is_capacity_error',
                          side_effect=RuntimeError('bad override')):
            exc = _inject(buyer, _response(404, NO_HUBS_BODY))
        assert isinstance(exc, LeadBuyerRejectedError)

    def test_the_detection_is_the_connectors_own(self, hypernet_buyer):
        """The opt-in is a property of the CONNECTOR CLASS, not of anything
        _request() infers — so the same judgement holds when the method is
        called directly, without a request in flight."""
        connector = HypernetConnector(hypernet_buyer)
        assert connector.is_capacity_error(404, _response(404, NO_HUBS_BODY))
        assert not connector.is_capacity_error(400, _response(400, NO_HUBS_BODY))
        assert not LeadBuyerConnector(hypernet_buyer).is_capacity_error(
            404, _response(404, NO_HUBS_BODY))


class TestHierarchy:
    """The class graph IS the contract — an `except` chain elsewhere in the
    codebase behaves correctly only because of these relationships."""

    def test_capacity_is_retryable_by_default_for_handlers_that_dont_know_it(self):
        """Subclassing the RETRYABLE base is what makes an unaware handler do
        the safe thing. If this ever became a LeadBuyerRejectedError
        subclass, every existing terminal handler would swallow it and the
        whole distinction would buy nothing — silently."""
        assert issubclass(LeadBuyerCapacityError, LeadBuyerError)
        assert not issubclass(LeadBuyerCapacityError, LeadBuyerRejectedError)
        assert not issubclass(LeadBuyerRejectedError, LeadBuyerCapacityError)

    def test_capacity_and_rejected_are_order_independent_siblings(self):
        """Neither catches the other, so their relative order in an `except`
        chain cannot silently disable one — unlike the base, which must come
        after both."""
        try:
            raise LeadBuyerCapacityError('no hubs', status_code=404)
        except LeadBuyerRejectedError:
            pytest.fail('LeadBuyerRejectedError caught a capacity error')
        except LeadBuyerCapacityError:
            pass


@pytest.mark.django_db
class TestTaskHandling:
    """What inject_lead_task actually does with one."""

    @pytest.fixture
    def injection(self, hypernet_buyer, lead):
        return LeadInjection.objects.create(
            lead=lead, buyer=hypernet_buyer, status=LeadInjection.STATUS_PENDING)

    @pytest.fixture
    def lead(self, db, brand):
        return Lead.objects.create(
            intake_channel=Lead.CHANNEL_AFFILIATE_API, brand=brand,
            first_name='Michel', last_name='Da Silva',
            email='maikelazevedo@hotmail.com', phone='+5545988343630',
            country_iso2='BR')

    def _run(self, injection):
        from leadgen.tasks import inject_lead_task

        with patch('leadgen.connectors.requests.request',
                   return_value=_response(404, NO_HUBS_BODY)):
            try:
                inject_lead_task(injection.pk)
            except Exception as exc:  # noqa: BLE001 — Celery's Retry, asserted on below
                return exc
        return None

    def test_the_lead_is_not_rejected_and_is_scheduled_to_retry(self, injection, lead):
        """The whole point. Before this change these three assertions read
        status=failed / lead=rejected / next_retry_at=None."""
        self._run(injection)
        injection.refresh_from_db()
        lead.refresh_from_db()

        assert injection.status == LeadInjection.STATUS_PENDING
        assert lead.status != Lead.STATUS_REJECTED
        assert injection.next_retry_at is not None
        assert 'No hubs available' in injection.failure_reason

    def test_the_first_wait_is_the_capacity_schedule_not_the_transient_one(self, injection):
        """60s is the network-hiccup schedule. A closed hub does not reopen
        in 60 seconds, and burning the budget at that cadence is how the
        outage outlives the retries. Asserts the actual scheduled delay, so
        this fails if the branch ever falls back to RETRY_BACKOFFS."""
        from django.utils import timezone

        before = timezone.now()
        retry = self._run(injection)
        injection.refresh_from_db()

        expected = LeadInjection.CAPACITY_RETRY_BACKOFFS[0]
        delay = (injection.next_retry_at - before).total_seconds()
        assert expected <= delay <= expected + 30, (
            f'scheduled {delay:.0f}s away, expected ~{expected}s '
            f'(RETRY_BACKOFFS[0] is {LeadInjection.RETRY_BACKOFFS[0]}s)')
        # And Celery was actually told to come back — a next_retry_at written
        # without self.retry() would leave the injection parked forever.
        #
        # Called directly (not via apply_async) Celery's request has
        # called_directly=True, so self.retry() re-raises the ORIGINAL
        # exception instead of Retry. Either way it propagates, and that is
        # the signal: both non-retrying capacity paths return normally, so
        # an exception escaping this task can only have come from retry().
        assert isinstance(retry, LeadBuyerCapacityError)

    def test_it_gives_up_only_after_the_whole_schedule(self, injection, lead):
        """attempts is persisted, so it survives across Celery retries; walk
        it to the end and confirm the last backoff is actually USED before
        the lead is given up on."""
        backoffs = LeadInjection.CAPACITY_RETRY_BACKOFFS
        LeadInjection.objects.filter(pk=injection.pk).update(attempts=len(backoffs) - 1)

        self._run(injection)
        injection.refresh_from_db()
        assert injection.status == LeadInjection.STATUS_PENDING, (
            'gave up while a backoff was still unused — the `<` off-by-one')

        self._run(injection)
        injection.refresh_from_db()
        lead.refresh_from_db()
        assert injection.status == LeadInjection.STATUS_FAILED
        assert lead.status == Lead.STATUS_FAILED

    def test_exhaustion_is_failed_not_rejected(self, injection, lead):
        """Nobody ever evaluated this lead. Recording a verdict that was
        never given would overstate the buyer's rejection rate in every
        report built on those counts."""
        LeadInjection.objects.filter(pk=injection.pk).update(
            attempts=len(LeadInjection.CAPACITY_RETRY_BACKOFFS))
        self._run(injection)
        lead.refresh_from_db()
        assert lead.status == Lead.STATUS_FAILED
        assert lead.status != Lead.STATUS_REJECTED

    def test_max_retries_clears_the_longest_schedule(self):
        """Pins tasks._MAX_INJECTION_RETRIES against the model's list, which
        it cannot import. Below it, Celery raises MaxRetriesExceededError
        part-way through the schedule and the lead dies at whatever attempt
        the cap lands on."""
        from leadgen import tasks

        assert tasks._MAX_INJECTION_RETRIES >= len(LeadInjection.CAPACITY_RETRY_BACKOFFS)
        assert tasks._MAX_INJECTION_RETRIES >= len(LeadInjection.RETRY_BACKOFFS)

    def test_a_chain_managed_lead_cascades_instead_of_waiting(self, injection, lead):
        """With a buyer left to try, six hours of waiting is the wrong
        trade — time-to-contact is what decides whether a lead converts, and
        a closed hub is exactly what failover is for."""
        LeadInjection.objects.filter(pk=injection.pk).update(chain_managed=True)
        injection.refresh_from_db()

        with patch('leadgen.failover.has_untried_buyer', return_value=True), \
             patch('leadgen.failover.advance_chain') as advance:
            self._run(injection)

        injection.refresh_from_db()
        advance.assert_called_once_with(lead.pk)
        assert injection.status == LeadInjection.STATUS_FAILED
        assert injection.next_retry_at is None, 'cascaded AND scheduled a retry'

    def test_a_manual_inject_now_schedules_a_real_retry(self, lead, hypernet_buyer):
        """End to end, through the surface an operator actually uses.

        services.start_injection(synchronous=True) backs every manual "inject
        now" button, including the Django admin action — the thing someone
        reaches for when a buyer has been refusing leads. It runs the task
        DIRECTLY, so Celery's self.retry() enqueues nothing; without the
        hand-off in services._hand_pending_retry_to_celery the lead parks at
        PENDING with a next_retry_at that never fires, and the operator has
        no way to tell.
        """
        from leadgen.services import start_injection

        with patch('leadgen.connectors.requests.request',
                   return_value=_response(404, NO_HUBS_BODY)), \
             patch('leadgen.services.inject_lead_task.apply_async') as queued:
            injection = start_injection(lead, hypernet_buyer, synchronous=True)

        assert injection.status == LeadInjection.STATUS_PENDING
        assert injection.next_retry_at is not None
        queued.assert_called_once_with((injection.pk,), eta=injection.next_retry_at)

    def test_a_chain_managed_lead_with_nowhere_to_go_still_waits(self, injection):
        """The ChainPulse case: chain-managed, but every buyer tried.
        Cascading resolves to UNROUTED, i.e. the bin — so waiting wins."""
        LeadInjection.objects.filter(pk=injection.pk).update(chain_managed=True)
        injection.refresh_from_db()

        with patch('leadgen.failover.has_untried_buyer', return_value=False), \
             patch('leadgen.failover.advance_chain') as advance:
            self._run(injection)

        injection.refresh_from_db()
        advance.assert_not_called()
        assert injection.status == LeadInjection.STATUS_PENDING
        assert injection.next_retry_at is not None
