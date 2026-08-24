"""Pins the Hypernet status vocabulary that the ChainPulse affiliate's LIVE
postbacks are derived from.

WHY THIS EXISTS — once an AffiliateOfferLink is LIVE, a buyer status string
travels all the way to the affiliate's postback URL unattended
(status_sync.apply_status_change -> dispatch_postbacks_for_event). Two silent
failure modes follow, and neither shows up as an error:

  1. A status we stop mapping stops reporting. `map_buyer_status` returns
     needs_review and NO postback fires — correct (never guess), but from the
     affiliate's side the lead simply goes quiet.
  2. A status remapped to the wrong canonical value reports the WRONG thing.
     `deposited` -> `ftd` is billable; getting that edge wrong is a money bug,
     not a display bug.

The values asserted here were probed off the LIVE desperados box on
2026-08-17 (full window, every row they hold) — see
docs/hypernet-status-endpoint.md. They are a record of what the box actually
emits, so if Hypernet changes their vocabulary this test is where that shows
up first, deliberately, instead of in an affiliate's missing revenue.
"""
import pytest

from leadgen import canonical_status
from leadgen.management.commands.seed_hypernet_box import DEFAULT_STATUS_MAPPING
from leadgen.models import BoxType, LeadBuyer
from leadgen.status_sync import map_buyer_status

# Probed 2026-08-17 against the live box, re-verified 2026-08-24 against
# Badboys. registration.status is their NORMALIZED field — the one
# leadgen.connectors.HypernetConnector.parse_status_sync_results reads — not
# the free-text rawStatus beside it.
OBSERVED_LIVE_VOCABULARY = {
    'sent': canonical_status.PENDING,
    'deposited': canonical_status.FTD,
}


@pytest.fixture
def hypernet_box(db):
    """The BoxType exactly as seed_hypernet_box builds it in production.

    THE MAPPING IS IMPORTED, NOT RETYPED, and that is the whole point. This
    fixture used to hardcode {'sent': 'pending', 'deposited': 'ftd'} while its
    docstring claimed to mirror production — but production's
    default_status_mapping was {} the entire time, because the seed command
    hardcoded {} too. Every assertion below passed against a mapping that
    existed only inside this file, so the tests stayed green while live
    Hypernet deposits landed as needs_review and no affiliate could see a
    single conversion through GET /api/leads?status=ftd.

    Importing the seed's own constant is what makes the green meaningful: a
    mapping that is missing from the seeded box now fails here.
    """
    return BoxType.objects.create(
        name='Hypernet', slug='hypernet-vocab',
        connector_class='leadgen.connectors.HypernetConnector',
        auth_type=BoxType.AUTH_API_KEY_HEADER, auth_param_name='x-api-key',
        single_endpoint_path='/api/external/integration/lead',
        fetch_endpoint_path='/api/external/integration/lead',
        default_status_mapping=DEFAULT_STATUS_MAPPING,
    )


@pytest.fixture
def hypernet_buyer(db, brand, hypernet_box):
    return LeadBuyer.objects.create(
        brand=brand, box_type=hypernet_box, name='Hypernet - vocab', slug='hypernet-vocab',
        is_active=True, auto_inject=False, base_url='https://desperados.hn-crm.test',
    )


@pytest.mark.django_db
class TestLiveVocabularyIsFullyMapped:
    @pytest.mark.parametrize('raw,expected', sorted(OBSERVED_LIVE_VOCABULARY.items()))
    def test_every_observed_status_maps_to_its_canonical_value(self, hypernet_buyer, raw, expected):
        canonical, needs_review = map_buyer_status(hypernet_buyer, raw)
        assert needs_review is False, f'{raw!r} would go silent — no postback reaches the affiliate'
        assert canonical == expected

    def test_deposited_is_the_billable_status(self, hypernet_buyer):
        """Guards the money edge specifically: `deposited` must land on FTD,
        the status the affiliate is paid on. A drift to `pending` silently
        under-reports revenue; a drift the other way bills for nothing."""
        canonical, _ = map_buyer_status(hypernet_buyer, 'deposited')
        assert canonical == canonical_status.FTD

    def test_mapped_values_are_real_canonical_statuses(self, hypernet_buyer):
        for raw in OBSERVED_LIVE_VOCABULARY:
            canonical, _ = map_buyer_status(hypernet_buyer, raw)
            assert canonical in canonical_status.VALUES


@pytest.mark.django_db
class TestUnknownStatusStaysSilentRatherThanGuessing:
    def test_an_unseen_status_is_flagged_for_review_not_mapped(self, hypernet_buyer):
        """If Hypernet adds a disposition (spec §3.2: never drop or guess), it
        must surface as review — NOT be coerced onto a neighbouring canonical
        value, which would report a status the buyer never asserted."""
        canonical, needs_review = map_buyer_status(hypernet_buyer, 'callback_scheduled')
        assert canonical is None
        assert needs_review is True

    def test_raw_status_free_text_is_not_a_mapping_key(self, hypernet_buyer):
        """rawStatus values seen live ('No answer', 'NoAnswer', 'Test Lead')
        are broker free text — two spellings of one disposition in a five-row
        sample. They must never resolve through status_mapping; only
        registration.status does."""
        for raw_text in ('No answer', 'NoAnswer', 'Test Lead'):
            canonical, needs_review = map_buyer_status(hypernet_buyer, raw_text)
            assert canonical is None
            assert needs_review is True

    def test_blank_status_is_not_review_worthy(self, hypernet_buyer):
        """"The buyer has not reported yet" is not a mapping failure."""
        canonical, needs_review = map_buyer_status(hypernet_buyer, '')
        assert canonical is None
        assert needs_review is False


@pytest.mark.django_db
class TestTheSeededBoxCanMapItsOwnVocabulary:
    """End-to-end over the seed command itself.

    The class above tests a BoxType built in-process from DEFAULT_STATUS_MAPPING,
    which proves the constant is right but not that the command WRITES it.
    Those are different failures and the second one is what actually happened:
    the constant did not exist and `default_status_mapping={}` was passed as a
    literal, so the seeded box could not map a single status.
    """

    def test_seeding_produces_a_box_that_maps_deposited_to_ftd(self, brand):
        from django.core.management import call_command

        call_command('seed_hypernet_box', verbosity=0)
        box = BoxType.objects.get(slug='hypernet')
        buyer = LeadBuyer.objects.create(
            brand=brand, box_type=box, name='Seeded', slug='hypernet-seeded',
            is_active=True, auto_inject=False, base_url='https://seeded.hn-crm.test',
        )
        canonical, needs_review = map_buyer_status(buyer, 'deposited')
        assert needs_review is False, (
            'the seeded Hypernet box cannot map its own deposit status — every '
            'conversion will land as needs_review and stay invisible to the affiliate')
        assert canonical == canonical_status.FTD

    def test_seeding_is_idempotent_and_does_not_blank_the_mapping(self, brand):
        """update_or_create rewrites `defaults` wholesale, so a re-seed is
        exactly how a mapping gets silently reset to {}. Re-running must leave
        it intact."""
        from django.core.management import call_command

        call_command('seed_hypernet_box', verbosity=0)
        call_command('seed_hypernet_box', verbosity=0)
        box = BoxType.objects.get(slug='hypernet')
        assert box.default_status_mapping == DEFAULT_STATUS_MAPPING
        assert box.default_status_mapping, 'a re-seed blanked the status mapping'
