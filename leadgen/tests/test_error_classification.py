"""Every failure mode _request() can produce maps to exactly one of three
outcomes — retryable, clean-reject, or ambiguous. This file pins that table.

Why it earns its own file: the classification is the difference between
"retry in a minute", "give it to a competitor now", and "stop, a human must
look at this". Getting it wrong is not a crash — it is a lead sold twice, or
a lead handed to a competitor the intended buyer would have taken seconds
later. Both are silent and both cost money.

Two ordering traps are pinned explicitly, because both collapse SILENTLY:
  * requests.ConnectTimeout subclasses BOTH ConnectionError and Timeout,
    while ReadTimeout subclasses only Timeout — catch the wrong one first
    and the double-sell guard evaporates.
  * LeadBuyerRejectedError and LeadBuyerAmbiguousError both subclass
    LeadBuyerError — an `except` chain that tests the base first catches
    everything and neither guard ever fires.

No network: requests.request is mocked, same pattern as test_connectors.py.
"""
from unittest.mock import MagicMock, patch

import pytest
import requests

from leadgen.connectors import (
    LeadBuyerAmbiguousError, LeadBuyerConnector, LeadBuyerError, LeadBuyerRejectedError,
)
from leadgen.models import Lead


def _lead():
    return Lead(intake_channel=Lead.CHANNEL_LANDING_PAGE,
                email='jane@test.com', phone='+15551234567')


def _raise_from_status(buyer, status_code):
    """Drive _request() to a real HTTP failure and return the exception."""
    connector = LeadBuyerConnector(buyer)
    resp = MagicMock(ok=False, status_code=status_code, text=f'body for {status_code}')
    with patch('leadgen.connectors.requests.request', return_value=resp):
        with pytest.raises(LeadBuyerError) as exc_info:
            connector.inject_lead(_lead())
    return exc_info.value


def _raise_from_transport(buyer, exc):
    connector = LeadBuyerConnector(buyer)
    with patch('leadgen.connectors.requests.request', side_effect=exc):
        with pytest.raises(LeadBuyerError) as exc_info:
            connector.inject_lead(_lead())
    return exc_info.value


@pytest.mark.django_db
class TestTheClassificationTable:
    """One case per row of LeadBuyerError's documented table."""

    @pytest.mark.parametrize('code', [400, 401, 403, 404, 409, 422])
    def test_4xx_except_429_is_a_clean_reject(self, buyer, code):
        exc = _raise_from_status(buyer, code)
        assert isinstance(exc, LeadBuyerRejectedError)
        assert not isinstance(exc, LeadBuyerAmbiguousError)
        assert exc.status_code == code

    def test_429_is_retryable_not_a_reject(self, buyer):
        """A 429 is "slow down", not "we looked and said no". Cascading it
        would hand the lead to a competitor when the intended buyer would
        have taken it seconds later."""
        exc = _raise_from_status(buyer, 429)
        assert type(exc) is LeadBuyerError
        assert not isinstance(exc, LeadBuyerRejectedError)
        assert not isinstance(exc, LeadBuyerAmbiguousError)

    @pytest.mark.parametrize('code,expected', [
        (428, LeadBuyerRejectedError),   # just below the carve-out
        (429, LeadBuyerError),           # the carve-out itself
        (430, LeadBuyerRejectedError),   # just above it
    ])
    def test_the_429_boundary_is_exact(self, buyer, code, expected):
        """The carve-out is one status code wide. An off-by-one here either
        cascades a rate-limit or retries a rejection 3x for nothing."""
        exc = _raise_from_status(buyer, code)
        assert type(exc) is expected

    def test_500_is_ambiguous(self, buyer):
        """Their application took the request and then fell over — possibly
        after creating the lead."""
        exc = _raise_from_status(buyer, 500)
        assert isinstance(exc, LeadBuyerAmbiguousError)

    @pytest.mark.parametrize('code', [502, 503, 504])
    def test_gateway_5xx_is_retryable_not_ambiguous(self, buyer, code):
        """A gateway/unavailable response means the request never reached
        the buyer's application, so nothing was created."""
        exc = _raise_from_status(buyer, code)
        assert type(exc) is LeadBuyerError
        assert not isinstance(exc, LeadBuyerAmbiguousError)

    def test_read_timeout_is_ambiguous(self, buyer):
        """The request WAS sent and we never heard back — the classic
        double-sell vector."""
        exc = _raise_from_transport(buyer, requests.ReadTimeout('timed out'))
        assert isinstance(exc, LeadBuyerAmbiguousError)

    @pytest.mark.parametrize('exc', [
        requests.ConnectTimeout('connect timed out'),
        requests.ConnectionError('refused'),
    ])
    def test_connect_failures_are_retryable(self, buyer, exc):
        """The buyer provably never received it, so retrying is safe."""
        raised = _raise_from_transport(buyer, exc)
        assert type(raised) is LeadBuyerError
        assert not isinstance(raised, LeadBuyerAmbiguousError)

    def test_unparseable_2xx_is_ambiguous(self, buyer):
        """They said OK in a shape we cannot read. Whether the lead landed
        is exactly what we cannot determine."""
        connector = LeadBuyerConnector(buyer)
        resp = MagicMock(ok=True, status_code=200, content=b'<html>hi</html>')
        resp.json.side_effect = ValueError('no json')
        with patch('leadgen.connectors.requests.request', return_value=resp):
            with pytest.raises(LeadBuyerAmbiguousError):
                connector.inject_lead(_lead())


@pytest.mark.django_db
class TestConnectTimeoutOrderingTrap:
    """requests.ConnectTimeout subclasses ConnectionError AND Timeout;
    ReadTimeout subclasses only Timeout. Catching the broad transport case
    before ReadTimeout would classify a read timeout as retryable and
    reopen the double-sell."""

    def test_connect_timeout_really_does_subclass_both(self):
        assert issubclass(requests.ConnectTimeout, requests.ConnectionError)
        assert issubclass(requests.ConnectTimeout, requests.Timeout)
        assert not issubclass(requests.ReadTimeout, requests.ConnectionError)

    def test_the_two_timeouts_classify_differently(self, buyer):
        read = _raise_from_transport(buyer, requests.ReadTimeout('x'))
        connect = _raise_from_transport(buyer, requests.ConnectTimeout('x'))
        assert isinstance(read, LeadBuyerAmbiguousError)
        assert not isinstance(connect, LeadBuyerAmbiguousError)


@pytest.mark.django_db
class TestExceptOrderingContract:
    """Both subclasses inherit from LeadBuyerError so that existing
    ``except LeadBuyerError`` handlers keep catching them. The cost of that
    choice is that handler ORDER becomes load-bearing — these tests make the
    trap executable rather than a docstring nobody reads."""

    def test_both_subclass_the_base_so_existing_handlers_still_catch_them(self):
        assert issubclass(LeadBuyerRejectedError, LeadBuyerError)
        assert issubclass(LeadBuyerAmbiguousError, LeadBuyerError)
        assert not issubclass(LeadBuyerAmbiguousError, LeadBuyerRejectedError)
        assert not issubclass(LeadBuyerRejectedError, LeadBuyerAmbiguousError)

    @staticmethod
    def _classify_correct_order(exc):
        try:
            raise exc
        except LeadBuyerAmbiguousError:
            return 'quarantine'
        except LeadBuyerRejectedError:
            return 'cascade'
        except LeadBuyerError:
            return 'retry'

    @staticmethod
    def _classify_base_first(exc):
        """The wrong wiring: base first swallows both subclasses."""
        try:
            raise exc
        except LeadBuyerError:
            return 'retry'
        except LeadBuyerAmbiguousError:  # pragma: no cover — unreachable
            return 'quarantine'
        except LeadBuyerRejectedError:  # pragma: no cover — unreachable
            return 'cascade'

    @pytest.mark.parametrize('exc,expected', [
        (LeadBuyerAmbiguousError('unknown'), 'quarantine'),
        (LeadBuyerRejectedError('nope', status_code=400), 'cascade'),
        (LeadBuyerError('try later', status_code=429), 'retry'),
    ])
    def test_correct_order_routes_each_outcome(self, exc, expected):
        assert self._classify_correct_order(exc) == expected

    @pytest.mark.parametrize('exc', [
        LeadBuyerAmbiguousError('unknown'),
        LeadBuyerRejectedError('nope', status_code=400),
    ])
    def test_base_first_silently_collapses_every_guard(self, exc):
        """THE trap, pinned. Base-first is not a crash and not a warning —
        it silently retries an ambiguous outcome (double-sell) and retries a
        clean reject (wasted latency). If the orchestrator is ever wired this
        way, this is what it does."""
        assert self._classify_base_first(exc) == 'retry'


@pytest.mark.django_db
class TestBehaviorChangeForLiveBuyers:
    """These reclassifications change how the LIVE op-brandy box behaves.
    Pinned so the change is visible in the suite, not just the commit
    message."""

    @pytest.mark.parametrize('code', [400, 422])
    def test_4xx_no_longer_burns_the_retry_budget(self, buyer, code):
        """Previously a 4xx raised plain LeadBuyerError -> 3 retries with
        backoff (60s/300s/1800s) before the chain advanced. Now it cascades
        immediately."""
        assert isinstance(_raise_from_status(buyer, code), LeadBuyerRejectedError)

    @pytest.mark.parametrize('code', [500])
    def test_500_no_longer_cascades_to_a_competitor(self, buyer, code):
        """Previously a 500 retried then cascaded — handing the lead to
        another buyer even though the first may have created it."""
        assert isinstance(_raise_from_status(buyer, code), LeadBuyerAmbiguousError)
