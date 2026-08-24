"""A buyer that is working the leads must be VISIBLE to the affiliate.

WHAT WENT WRONG. HypernetConnector read `registration.status` and ignored
`rawStatus` beside it, because free text "cannot be mapped safely". But on a
live box the normalized field is effectively binary — 'sent' from injection
until a deposit flips it to 'deposited' — and every disposition the call centre
records lands only in rawStatus. Three Badboys leads sat at `status='sent'`
with rawStatus of 'voice mail', 'voice mail' and 'not register'. The affiliate
saw `pending` on all three and concluded the buyer was ignoring their traffic.

The fix has two independent halves and this file pins both, because either one
alone leaves the affiliate short:

  * VISIBILITY does not depend on anyone having written a mapping. The raw
    string becomes Lead.buyer_status, which is on the pull API's serializer.
  * MAPPING drives canonical_status, and an unmapped disposition still goes to
    needs_review rather than being guessed at.
"""
import pytest

from leadgen import canonical_status
from leadgen.connectors import HypernetConnector
from leadgen.models import BoxType, LeadBuyer
from leadgen.status_sync import map_buyer_status


@pytest.fixture
def hypernet_box(db):
    return BoxType.objects.create(
        name='Hypernet', slug='hypernet-raw',
        connector_class='leadgen.connectors.HypernetConnector',
        auth_type=BoxType.AUTH_API_KEY_HEADER, auth_param_name='x-api-key',
        single_endpoint_path='/api/external/integration/lead',
        fetch_endpoint_path='/api/external/integration/lead',
        default_status_mapping={'sent': 'pending', 'deposited': 'ftd'},
    )


@pytest.fixture
def buyer(db, brand, hypernet_box):
    return LeadBuyer.objects.create(
        brand=brand, box_type=hypernet_box, name='Badboys-like', slug='badboys-like',
        is_active=True, base_url='https://box.test',
    )


def _row(status, raw_status, *, deposited=False, ext='ext-1'):
    return {'rows': [{
        'id': ext,
        'registration': {'status': status, 'rawStatus': raw_status},
        'isDeposited': deposited,
        'depositedAt': '2026-08-24T11:00:00.000Z' if deposited else None,
        'geo': 'PL',
    }]}


class TestTheDispositionReachesUs:
    def test_a_worked_lead_reports_its_disposition_not_sent(self, buyer):
        """The exact live shape: status stuck on 'sent', the real outcome in
        rawStatus. Reporting 'sent' here is what made the buyer look idle."""
        result = HypernetConnector(buyer).parse_status_sync_results(
            _row('sent', 'voice mail'))[0]
        assert result['buyer_status'] == 'voice mail'

    def test_an_untouched_lead_still_reports_sent(self, buyer):
        """No disposition yet is not the same as a disposition. With rawStatus
        empty the normalized status must come through unchanged, or a brand new
        lead would report as blank instead of pending."""
        result = HypernetConnector(buyer).parse_status_sync_results(
            _row('sent', ''))[0]
        assert result['buyer_status'] == 'sent'

    def test_a_deposit_is_never_overridden_by_free_text(self, buyer):
        """THE MONEY EDGE. The QA box returns rawStatus 'Test Lead' beside a
        real deposit. 'deposited' is committal and corroborated by isDeposited;
        letting free text win here would unreport a billable conversion."""
        result = HypernetConnector(buyer).parse_status_sync_results(
            _row('deposited', 'Test Lead', deposited=True))[0]
        assert result['buyer_status'] == 'deposited'
        assert result['deposit'] is True

    def test_unknown_normalized_statuses_win_over_raw_status(self, buyer):
        """NON_COMMITTAL_STATUSES is an allowlist, not a denylist. If Hypernet
        adds a real normalized status we have never seen, it must be treated as
        a verdict — the safe default is to trust the normalized field."""
        result = HypernetConnector(buyer).parse_status_sync_results(
            _row('some_new_status', 'voice mail'))[0]
        assert result['buyer_status'] == 'some_new_status'

    def test_surrounding_whitespace_does_not_hide_a_disposition(self, buyer):
        result = HypernetConnector(buyer).parse_status_sync_results(
            _row(' sent ', ' voice mail '))[0]
        assert result['buyer_status'] == 'voice mail'


@pytest.mark.django_db
class TestVisibilityDoesNotWaitOnAMapping:
    def test_an_unmapped_disposition_is_still_reported_verbatim(self, buyer):
        """The affiliate sees what the buyer said even before an operator has
        decided what it means canonically. This is the whole point: visibility
        must not be gated on our own configuration."""
        result = HypernetConnector(buyer).parse_status_sync_results(
            _row('sent', 'some brand new disposition'))[0]
        assert result['buyer_status'] == 'some brand new disposition'

    def test_but_it_does_not_invent_a_canonical_status(self, buyer):
        canonical, needs_review = map_buyer_status(buyer, 'some brand new disposition')
        assert canonical is None
        assert needs_review is True


@pytest.mark.django_db
class TestMappingIsCaseAndSpacingTolerant:
    """One live box produced both 'No answer' and 'NoAnswer' for a single
    disposition in a five-row sample. An operator writes the entry once."""

    @pytest.fixture
    def mapped_buyer(self, buyer):
        buyer.status_mapping = {'voice mail': 'no_answer'}
        buyer.save(update_fields=['status_mapping'])
        return buyer

    @pytest.mark.parametrize('spelling', [
        'voice mail', 'Voice Mail', 'VOICE MAIL', 'voicemail', ' voice  mail ',
    ])
    def test_spelling_variants_resolve(self, mapped_buyer, spelling):
        canonical, needs_review = map_buyer_status(mapped_buyer, spelling)
        assert needs_review is False
        assert canonical == canonical_status.NO_ANSWER

    def test_an_exact_entry_still_wins_over_the_folded_one(self, buyer):
        """The folded lookup is a FALLBACK. Where both could match, the exact
        key decides — otherwise adding this would have silently changed what
        an existing mapping resolves to."""
        buyer.status_mapping = {'Voice Mail': 'callback', 'voice mail': 'no_answer'}
        buyer.save(update_fields=['status_mapping'])
        assert map_buyer_status(buyer, 'Voice Mail')[0] == canonical_status.CALLBACK
        assert map_buyer_status(buyer, 'voice mail')[0] == canonical_status.NO_ANSWER

    def test_a_genuinely_unknown_status_is_still_review(self, mapped_buyer):
        assert map_buyer_status(mapped_buyer, 'wandered off') == (None, True)


@pytest.mark.django_db
class TestSetBuyerStatusMappingCommand:
    def test_it_merges_rather_than_replacing(self, buyer):
        from django.core.management import call_command

        buyer.status_mapping = {'existing': 'callback'}
        buyer.save(update_fields=['status_mapping'])
        call_command('set_buyer_status_mapping', '--buyer', buyer.slug,
                     '--map', '{"voice mail": "no_answer"}', verbosity=0)
        buyer.refresh_from_db()
        assert buyer.status_mapping == {'existing': 'callback', 'voice mail': 'no_answer'}

    def test_it_refuses_a_value_that_is_not_a_canonical_status(self, buyer):
        from django.core.management import call_command
        from django.core.management.base import CommandError

        with pytest.raises(CommandError, match='not canonical statuses'):
            call_command('set_buyer_status_mapping', '--buyer', buyer.slug,
                         '--map', '{"voice mail": "no-answer"}', verbosity=0)
        buyer.refresh_from_db()
        assert buyer.status_mapping == {}

    def test_dry_run_writes_nothing(self, buyer):
        from django.core.management import call_command

        call_command('set_buyer_status_mapping', '--buyer', buyer.slug,
                     '--map', '{"voice mail": "no_answer"}', '--dry-run', verbosity=0)
        buyer.refresh_from_db()
        assert buyer.status_mapping == {}
