"""Tests for the affiliate postback return path (leadgen/postback_delivery.py)
— HMAC signing, retry/backoff, macro rendering, and subscription filtering.
Mirrors public_api/tests/test_webhooks.py's structure closely (same
underlying pattern, deliberately reused rather than reinvented)."""
import hashlib
import hmac
from unittest.mock import MagicMock, patch

import pytest

from leadgen import canonical_status
from leadgen.models import AffiliateOfferLink, AffiliatePostbackConfig, Lead, LeadStatusEvent, PostbackDelivery
from leadgen.postback_delivery import _render_url, _sign, deliver_affiliate_postback, dispatch_postbacks_for_event
from leadgen.security import PostbackURLResolutionError, UnsafePostbackURLError
from leadgen.status_sync import apply_status_change, go_live


def _lead(**kwargs):
    defaults = dict(intake_channel=Lead.CHANNEL_AFFILIATE_API, email='postback@test.com', phone='+15551234567')
    defaults.update(kwargs)
    return Lead.objects.create(**defaults)


@pytest.mark.django_db
class TestSignAndRenderUrl:
    def test_sign_produces_sha256_hmac(self):
        secret = 'testsecret'
        payload = b'{"status":"ftd"}'
        sig = _sign(secret, payload)
        assert sig.startswith('sha256=')
        assert sig == 'sha256=' + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()

    def test_render_url_substitutes_all_macros(self, affiliate_user, offer):
        lead = _lead(affiliate=affiliate_user, offer=offer, source_id='sub-99')
        event = apply_status_change(lead, canonical_status.FTD, source=LeadStatusEvent.SOURCE_OPERATOR)
        url = _render_url(
            'https://aff.test/cb?lead={lead_id}&sub={source_id}&s={status}&t={status_time}&o={offer_id}&p={payout}',
            lead=lead, event=event,
        )
        assert f'lead={lead.pk}' in url
        assert 'sub=sub-99' in url
        assert 's=ftd' in url
        assert f'o={offer.pk}' in url
        assert 'p=' in url  # payout always blank — no per-lead payout model exists yet

    def test_render_url_leaves_unrelated_text_untouched(self, affiliate_user, offer):
        lead = _lead(affiliate=affiliate_user, offer=offer)
        event = apply_status_change(lead, canonical_status.NEW, source=LeadStatusEvent.SOURCE_OPERATOR)
        url = _render_url('https://aff.test/cb?static=1&lead={lead_id}', lead=lead, event=event)
        assert url == f'https://aff.test/cb?static=1&lead={lead.pk}'


@pytest.mark.django_db
class TestDispatchPostbacksForEvent:
    """Unit-level: builds a LeadStatusEvent directly (NOT via
    apply_status_change, which — since Phase 4.3 — already calls
    dispatch_postbacks_for_event itself) so these tests exercise the
    dispatch/filtering logic in isolation, with no double-dispatch risk."""

    def _event(self, lead, to_status):
        return LeadStatusEvent.objects.create(
            lead=lead, to_status=to_status, source=LeadStatusEvent.SOURCE_OPERATOR,
            applied=True, lead_seq=1)

    def test_no_affiliate_is_a_noop(self, offer):
        lead = _lead(intake_channel=Lead.CHANNEL_LANDING_PAGE, affiliate=None, offer=offer)
        event = self._event(lead, canonical_status.NEW)
        with patch('leadgen.postback_delivery.deliver_affiliate_postback') as mock_task:
            mock_task.delay = MagicMock()
            dispatch_postbacks_for_event(event)
        mock_task.delay.assert_not_called()

    def test_no_configs_is_a_noop(self, affiliate_user, offer):
        lead = _lead(affiliate=affiliate_user, offer=offer)
        event = self._event(lead, canonical_status.NEW)
        with patch('leadgen.postback_delivery.deliver_affiliate_postback') as mock_task:
            mock_task.delay = MagicMock()
            dispatch_postbacks_for_event(event)
        mock_task.delay.assert_not_called()

    def test_inactive_config_is_skipped(self, affiliate_user, offer):
        AffiliatePostbackConfig.objects.create(
            affiliate=affiliate_user, url='https://aff.test/cb', is_active=False)
        lead = _lead(affiliate=affiliate_user, offer=offer)
        event = self._event(lead, canonical_status.NEW)
        with patch('leadgen.postback_delivery.deliver_affiliate_postback') as mock_task:
            mock_task.delay = MagicMock()
            dispatch_postbacks_for_event(event)
        mock_task.delay.assert_not_called()

    def test_empty_subscribed_statuses_matches_everything(self, affiliate_user, offer):
        config = AffiliatePostbackConfig.objects.create(
            affiliate=affiliate_user, url='https://aff.test/cb', subscribed_statuses=[])
        lead = _lead(affiliate=affiliate_user, offer=offer)
        event = self._event(lead, canonical_status.CHARGEBACK)
        with patch('leadgen.postback_delivery.deliver_affiliate_postback') as mock_task:
            mock_task.delay = MagicMock()
            dispatch_postbacks_for_event(event)
        mock_task.delay.assert_called_once()
        delivery = PostbackDelivery.objects.get()
        assert delivery.config_id == config.pk

    def test_status_not_in_subscribed_list_is_skipped(self, affiliate_user, offer):
        AffiliatePostbackConfig.objects.create(
            affiliate=affiliate_user, url='https://aff.test/cb', subscribed_statuses=[canonical_status.FTD])
        lead = _lead(affiliate=affiliate_user, offer=offer)
        event = self._event(lead, canonical_status.NEW)
        with patch('leadgen.postback_delivery.deliver_affiliate_postback') as mock_task:
            mock_task.delay = MagicMock()
            dispatch_postbacks_for_event(event)
        mock_task.delay.assert_not_called()

    def test_subscribed_status_triggers_delivery(self, affiliate_user, offer):
        AffiliatePostbackConfig.objects.create(
            affiliate=affiliate_user, url='https://aff.test/cb', subscribed_statuses=[canonical_status.FTD])
        lead = _lead(affiliate=affiliate_user, offer=offer)
        event = self._event(lead, canonical_status.FTD)
        with patch('leadgen.postback_delivery.deliver_affiliate_postback') as mock_task:
            mock_task.delay = MagicMock()
            dispatch_postbacks_for_event(event)
        mock_task.delay.assert_called_once()


@pytest.mark.django_db
class TestApplyStatusChangeTriggersPostback:
    """The integration point: leadgen.status_sync.apply_status_change only
    dispatches for events that actually applied — spec §2.2/§5.1."""

    def test_applied_event_dispatches(self, affiliate_user, offer):
        AffiliatePostbackConfig.objects.create(affiliate=affiliate_user, url='https://aff.test/cb')
        lead = _lead(affiliate=affiliate_user, offer=offer)
        with patch('leadgen.postback_delivery.deliver_affiliate_postback') as mock_task:
            mock_task.delay = MagicMock()
            apply_status_change(lead, canonical_status.FTD, source=LeadStatusEvent.SOURCE_OPERATOR)
        mock_task.delay.assert_called_once()

    def test_recorded_but_not_applied_never_dispatches(self, affiliate_user, offer):
        """A buyer status recorded during TESTING must stay silent — nothing
        actually changed from the affiliate's point of view."""
        AffiliatePostbackConfig.objects.create(affiliate=affiliate_user, url='https://aff.test/cb')
        lead = _lead(affiliate=affiliate_user, offer=offer)
        with patch('leadgen.postback_delivery.deliver_affiliate_postback') as mock_task:
            mock_task.delay = MagicMock()
            event = apply_status_change(lead, canonical_status.FTD, source=LeadStatusEvent.SOURCE_BUYER)
        assert event.applied is False
        mock_task.delay.assert_not_called()

    def test_repeated_buyer_report_of_the_same_status_is_silent(self, affiliate_user, offer):
        """The 30-minute buyer poll re-reports an unchanged status forever.
        Only the first one is news: the repeats must write no event and fire
        no postback, or a single live lead generates 48 identical postbacks a
        day."""
        AffiliatePostbackConfig.objects.create(affiliate=affiliate_user, url='https://aff.test/cb')
        lead = _lead(affiliate=affiliate_user, offer=offer)
        link = AffiliateOfferLink.objects.create(affiliate=affiliate_user, offer=offer)
        go_live(link, actor=affiliate_user)

        with patch('leadgen.postback_delivery.deliver_affiliate_postback.delay') as mock_delay:
            first = apply_status_change(lead, canonical_status.PENDING, source=LeadStatusEvent.SOURCE_BUYER)
            repeats = [
                apply_status_change(lead, canonical_status.PENDING, source=LeadStatusEvent.SOURCE_BUYER)
                for _ in range(5)
            ]
        assert first is not None and first.applied is True
        assert repeats == [None] * 5
        assert mock_delay.call_count == 1
        assert LeadStatusEvent.objects.filter(
            lead=lead, source=LeadStatusEvent.SOURCE_BUYER).count() == 1

    def test_a_real_buyer_transition_after_repeats_still_fires(self, affiliate_user, offer):
        """Deduplication must not swallow the move that matters."""
        AffiliatePostbackConfig.objects.create(affiliate=affiliate_user, url='https://aff.test/cb')
        lead = _lead(affiliate=affiliate_user, offer=offer)
        link = AffiliateOfferLink.objects.create(affiliate=affiliate_user, offer=offer)
        go_live(link, actor=affiliate_user)

        with patch('leadgen.postback_delivery.deliver_affiliate_postback.delay') as mock_delay:
            apply_status_change(lead, canonical_status.PENDING, source=LeadStatusEvent.SOURCE_BUYER)
            apply_status_change(lead, canonical_status.PENDING, source=LeadStatusEvent.SOURCE_BUYER)
            moved = apply_status_change(lead, canonical_status.FTD, source=LeadStatusEvent.SOURCE_BUYER)
        lead.refresh_from_db()
        assert moved is not None and moved.applied is True
        assert lead.canonical_status == canonical_status.FTD
        assert mock_delay.call_count == 2  # pending, then ftd — not the repeat

    def test_go_live_applies_a_status_the_buyer_already_reported_in_testing(self, affiliate_user, offer):
        """Regression: dedupe must be phase-aware. A buyer saying FTD during
        TESTING is recorded but not applied; after go-live the SAME status is
        authoritative for the first time and must take effect. Deduplicating on
        the buyer's previous word alone would strand the lead on its stale
        operator-set status until the buyer happened to change its mind."""
        AffiliatePostbackConfig.objects.create(affiliate=affiliate_user, url='https://aff.test/cb')
        lead = _lead(affiliate=affiliate_user, offer=offer)
        apply_status_change(lead, canonical_status.PENDING, source=LeadStatusEvent.SOURCE_OPERATOR)
        link = AffiliateOfferLink.objects.get(affiliate=affiliate_user, offer=offer)

        testing_event = apply_status_change(lead, canonical_status.FTD, source=LeadStatusEvent.SOURCE_BUYER)
        assert testing_event.applied is False
        # ...and the testing-phase repeat is still suppressed as pure noise.
        assert apply_status_change(lead, canonical_status.FTD, source=LeadStatusEvent.SOURCE_BUYER) is None

        go_live(link, actor=affiliate_user)
        with patch('leadgen.postback_delivery.deliver_affiliate_postback.delay') as mock_delay:
            live_event = apply_status_change(lead, canonical_status.FTD, source=LeadStatusEvent.SOURCE_BUYER)
        lead.refresh_from_db()
        assert live_event is not None and live_event.applied is True
        assert lead.canonical_status == canonical_status.FTD
        mock_delay.assert_called_once()

    def test_operator_reaffirming_a_status_is_always_recorded(self, affiliate_user, offer):
        """Only the buyer is deduplicated. An operator setting the status it
        already holds is a deliberate, audited act — but it still carries no
        news for the affiliate, so no postback fires."""
        AffiliatePostbackConfig.objects.create(affiliate=affiliate_user, url='https://aff.test/cb')
        lead = _lead(affiliate=affiliate_user, offer=offer)
        with patch('leadgen.postback_delivery.deliver_affiliate_postback.delay') as mock_delay:
            apply_status_change(lead, canonical_status.PENDING, source=LeadStatusEvent.SOURCE_OPERATOR)
            again = apply_status_change(lead, canonical_status.PENDING, source=LeadStatusEvent.SOURCE_OPERATOR)
        assert again is not None
        assert LeadStatusEvent.objects.filter(lead=lead).count() == 2
        assert mock_delay.call_count == 1

    def test_lead_seq_increments_monotonically_per_lead(self, affiliate_user, offer):
        lead = _lead(affiliate=affiliate_user, offer=offer)
        e1 = apply_status_change(lead, canonical_status.NEW, source=LeadStatusEvent.SOURCE_OPERATOR)
        e2 = apply_status_change(lead, canonical_status.TEST, source=LeadStatusEvent.SOURCE_OPERATOR)
        e3 = apply_status_change(lead, canonical_status.TEST_FTD, source=LeadStatusEvent.SOURCE_OPERATOR)
        assert [e1.lead_seq, e2.lead_seq, e3.lead_seq] == [1, 2, 3]

    def test_lead_seq_is_independent_per_lead(self, affiliate_user, offer):
        lead_a = _lead(affiliate=affiliate_user, offer=offer, email='a@test.com')
        lead_b = _lead(affiliate=affiliate_user, offer=offer, email='b@test.com')
        apply_status_change(lead_a, canonical_status.NEW, source=LeadStatusEvent.SOURCE_OPERATOR)
        e_a2 = apply_status_change(lead_a, canonical_status.TEST, source=LeadStatusEvent.SOURCE_OPERATOR)
        e_b1 = apply_status_change(lead_b, canonical_status.NEW, source=LeadStatusEvent.SOURCE_OPERATOR)
        assert e_a2.lead_seq == 2
        assert e_b1.lead_seq == 1  # lead_b's own first event, unaffected by lead_a's count

    def test_full_live_loop_buyer_status_reaches_signed_postback(self, affiliate_user, offer):
        """Spec §10 acceptance item 7: in LIVE, a buyer status normalizes to
        canonical and fires a signed postback to the affiliate."""
        config = AffiliatePostbackConfig.objects.create(affiliate=affiliate_user, url='https://aff.test/cb')
        lead = _lead(affiliate=affiliate_user, offer=offer)
        link = AffiliateOfferLink.objects.create(affiliate=affiliate_user, offer=offer)
        go_live(link, actor=affiliate_user)

        # Mock .delay() during apply_status_change so no real Celery
        # dispatch (and no real HTTP attempt to a fake domain) happens here
        # — the delivery task itself gets exercised deliberately, below.
        with patch('leadgen.postback_delivery.deliver_affiliate_postback.delay') as mock_delay:
            apply_status_change(lead, canonical_status.FTD, source=LeadStatusEvent.SOURCE_BUYER)
        mock_delay.assert_called_once()

        delivery = PostbackDelivery.objects.get(config=config)
        assert delivery.status == PostbackDelivery.STATUS_PENDING  # not yet actually delivered — task queued async

        mock_resp = MagicMock(status_code=200)
        mock_resp.raise_for_status.return_value = None
        # aff.test (RFC 2606 reserved) doesn't really resolve — Phase 7's
        # SSRF guard is tested in isolation in test_security.py, not here.
        with patch('leadgen.postback_delivery.validate_postback_url'), \
             patch('leadgen.postback_delivery.requests.post', return_value=mock_resp) as mock_post:
            deliver_affiliate_postback(delivery.pk)

        delivery.refresh_from_db()
        assert delivery.status == PostbackDelivery.STATUS_DELIVERED
        headers = mock_post.call_args.kwargs['headers']
        assert headers['X-Nexora-Signature'].startswith('sha256=')
        assert headers['X-Nexora-Event'] == 'lead.status.ftd'


@pytest.mark.django_db
class TestDeliverAffiliatePostbackTask:
    @pytest.fixture(autouse=True)
    def _skip_postback_url_ssrf_check(self):
        """These tests exercise signing/retry/payload logic against the
        reserved aff.test domain (RFC 2606), which doesn't really resolve.
        Phase 7's SSRF guard (leadgen.security.validate_postback_url) is
        unit-tested in isolation in test_security.py, not here."""
        with patch('leadgen.postback_delivery.validate_postback_url'):
            yield

    def _delivery(self, affiliate_user, offer, **kwargs):
        config = AffiliatePostbackConfig.objects.create(affiliate=affiliate_user, url='https://aff.test/cb')
        lead = _lead(affiliate=affiliate_user, offer=offer)
        event = apply_status_change(lead, canonical_status.FTD, source=LeadStatusEvent.SOURCE_OPERATOR)
        return PostbackDelivery.objects.create(
            config=config, status_event=event, url=config.url, **kwargs)

    def test_successful_delivery_marks_delivered(self, affiliate_user, offer):
        delivery = self._delivery(affiliate_user, offer)
        mock_resp = MagicMock(status_code=200)
        mock_resp.raise_for_status.return_value = None
        with patch('leadgen.postback_delivery.requests.post', return_value=mock_resp):
            deliver_affiliate_postback(delivery.pk)
        delivery.refresh_from_db()
        assert delivery.status == PostbackDelivery.STATUS_DELIVERED
        assert delivery.delivered_at is not None
        assert delivery.attempts == 1
        assert delivery.response_status_code == 200

    def test_failed_delivery_increments_attempts_and_schedules_retry(self, affiliate_user, offer):
        delivery = self._delivery(affiliate_user, offer)
        with patch('leadgen.postback_delivery.requests.post', side_effect=Exception('Connection refused')):
            try:
                deliver_affiliate_postback(delivery.pk)
            except Exception:
                pass
        delivery.refresh_from_db()
        assert delivery.attempts == 1
        assert delivery.last_error != ''
        assert delivery.next_retry_at is not None
        assert delivery.status == PostbackDelivery.STATUS_PENDING

    def test_max_retries_marks_failed(self, affiliate_user, offer):
        delivery = self._delivery(affiliate_user, offer, attempts=2)
        with patch('leadgen.postback_delivery.requests.post', side_effect=Exception('Timeout')):
            try:
                deliver_affiliate_postback(delivery.pk)
            except Exception:
                pass
        delivery.refresh_from_db()
        assert delivery.status == PostbackDelivery.STATUS_FAILED

    def test_already_delivered_is_not_resent(self, affiliate_user, offer):
        delivery = self._delivery(affiliate_user, offer, status=PostbackDelivery.STATUS_DELIVERED, attempts=1)
        with patch('leadgen.postback_delivery.requests.post') as mock_post:
            deliver_affiliate_postback(delivery.pk)
        mock_post.assert_not_called()

    def test_payload_carries_status_seq(self, affiliate_user, offer):
        delivery = self._delivery(affiliate_user, offer)
        mock_resp = MagicMock(status_code=200)
        mock_resp.raise_for_status.return_value = None
        with patch('leadgen.postback_delivery.requests.post', return_value=mock_resp) as mock_post:
            deliver_affiliate_postback(delivery.pk)
        import json
        sent_payload = json.loads(mock_post.call_args.kwargs['data'])
        assert sent_payload['status_seq'] == delivery.status_event.lead_seq
        assert sent_payload['status'] == canonical_status.FTD


@pytest.mark.django_db
class TestDeliveryTimeURLGuard:
    """How the delivery task reacts to the Phase 7 guard. Deliberately not a
    subclass of TestDeliverAffiliatePostbackTask — these tests need the real
    guard in the call path, not that class's autouse patch of it.

    The distinction under test: an unsafe destination is a verdict that can
    only repeat, so it fails permanently, while a resolver that didn't answer
    is a transient network condition and must retry — otherwise a DNS blip
    silently drops an affiliate's postbacks."""

    def _delivery(self, affiliate_user, offer, **kwargs):
        config = AffiliatePostbackConfig.objects.create(affiliate=affiliate_user, url='https://aff.test/cb')
        lead = _lead(affiliate=affiliate_user, offer=offer)
        event = apply_status_change(lead, canonical_status.FTD, source=LeadStatusEvent.SOURCE_OPERATOR)
        return PostbackDelivery.objects.create(
            config=config, status_event=event, url=config.url, **kwargs)

    def test_unsafe_destination_fails_permanently_without_requesting(self, affiliate_user, offer):
        delivery = self._delivery(affiliate_user, offer)
        with patch('leadgen.postback_delivery.validate_postback_url',
                   side_effect=UnsafePostbackURLError('resolves to a private or internal address')), \
             patch('leadgen.postback_delivery.requests.post') as mock_post:
            deliver_affiliate_postback(delivery.pk)
        delivery.refresh_from_db()
        mock_post.assert_not_called()
        assert delivery.status == PostbackDelivery.STATUS_FAILED
        assert delivery.next_retry_at is None
        assert 'private or internal' in delivery.last_error

    def test_unresolvable_host_schedules_a_retry(self, affiliate_user, offer):
        delivery = self._delivery(affiliate_user, offer)
        with patch('leadgen.postback_delivery.validate_postback_url',
                   side_effect=PostbackURLResolutionError('could not be resolved')), \
             patch('leadgen.postback_delivery.requests.post') as mock_post:
            try:
                deliver_affiliate_postback(delivery.pk)
            except Exception:
                pass
        delivery.refresh_from_db()
        mock_post.assert_not_called()
        assert delivery.status == PostbackDelivery.STATUS_PENDING
        assert delivery.attempts == 1
        assert delivery.next_retry_at is not None
        assert 'could not be resolved' in delivery.last_error

    def test_unresolvable_host_still_fails_after_max_retries(self, affiliate_user, offer):
        delivery = self._delivery(affiliate_user, offer, attempts=2)
        with patch('leadgen.postback_delivery.validate_postback_url',
                   side_effect=PostbackURLResolutionError('could not be resolved')):
            try:
                deliver_affiliate_postback(delivery.pk)
            except Exception:
                pass
        delivery.refresh_from_db()
        assert delivery.status == PostbackDelivery.STATUS_FAILED
