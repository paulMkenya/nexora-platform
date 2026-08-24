"""Phase 7's full acceptance suite (spec §10) — one end-to-end script per
scenario, walking the whole protocol hub the way a real integration would:
affiliate submits -> operator manages status in TESTING -> pair goes LIVE ->
a buyer status becomes authoritative -> a signed postback fires -> the
affiliate pulls the lead back and sees the same story. Every individual
piece already has its own focused unit tests elsewhere (test_api_views.py,
test_status_authority.py, test_postback_delivery.py, ...) — this file
proves they compose correctly end-to-end, which none of those files do on
their own."""
from unittest.mock import MagicMock, patch

import pytest
from rest_framework.test import APIClient

from leadgen import canonical_status
from leadgen.models import AffiliateOfferLink, AffiliatePostbackConfig, Lead, LeadStatusEvent, PostbackDelivery
from leadgen.status_sync import apply_status_change, go_live

SUBMIT_URL = '/api/leads/submit'
LIST_URL = '/api/leads'
STATUSES_URL = '/api/leads/statuses'


def _client_with_key(key):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f'ApiKey {key.secret}')
    return client


@pytest.fixture
def eligible_offer(db, brand):
    """Standalone Offer with an APPROVED+verified advertiser — mirrors
    test_api_views.py's own fixture of the same name exactly (the shared
    `offer` fixture's advertiser starts PENDING, which fails eligibility).

    Branded to the affiliate's own brand: under the brand-only ruling an
    unbranded offer is visible to no affiliate at all."""
    from django.contrib.auth import get_user_model

    from offer.models import Advertiser, Offer

    User = get_user_model()
    adv_user = User.objects.create_user(username='acc_flow_adv', password='pass', email='accadv@test.com')
    advertiser = Advertiser.objects.create(
        user=adv_user, company='AccFlowAdvCo', email='accadv@test.com',
        advertiser_status=Advertiser.AdvertiserStatus.APPROVED, email_verified=True,
    )
    return Offer.objects.create(
        title='Acceptance Flow Offer', tracking_link='https://t.accflow.test/click',
        brand=brand, advertiser=advertiser,
    )


@pytest.mark.django_db
class TestFullAcceptanceFlow:
    def test_submit_through_testing_go_live_buyer_status_postback_and_pull(
        self, affiliate_api_key, affiliate_user, eligible_offer,
    ):
        client = _client_with_key(affiliate_api_key)

        # 1. Affiliate submits a lead (spec §4) — starts in TESTING by
        # default, no AffiliateOfferLink row exists yet. maybe_auto_inject
        # is mocked, same as every other submit test in this suite — it's a
        # routing concern, not part of what this test is verifying.
        assert not AffiliateOfferLink.objects.filter(affiliate=affiliate_user, offer=eligible_offer).exists()
        with patch('leadgen.api_views.maybe_auto_inject'):
            resp = client.post(SUBMIT_URL, {
                'first_name': 'Accept', 'last_name': 'Ance', 'email': 'accept@test.com',
                'phone': '+15559998888', 'vertical': 'finance', 'source_id': 'acc-flow-1',
                'offer_id': eligible_offer.pk, 'country': 'US',
            }, format='json')
        assert resp.status_code == 201
        lead = Lead.objects.get(source_id='acc-flow-1', affiliate=affiliate_user)
        assert lead.country_iso2 == 'US'  # geo tie-in: affiliate-supplied country wins outright

        # 2. Operator sets a status manually while TESTING — this is the
        # authoritative source until go-live (spec §2).
        apply_status_change(lead, canonical_status.PENDING, source=LeadStatusEvent.SOURCE_OPERATOR)
        lead.refresh_from_db()
        assert lead.canonical_status == canonical_status.PENDING
        link = AffiliateOfferLink.objects.get(affiliate=affiliate_user, offer=eligible_offer)
        assert link.phase == AffiliateOfferLink.PHASE_TESTING

        # A buyer status arriving during TESTING is recorded, not applied —
        # the operator's own call above must not be clobbered by it.
        event = apply_status_change(lead, canonical_status.FTD, source=LeadStatusEvent.SOURCE_BUYER)
        assert event.applied is False
        lead.refresh_from_db()
        assert lead.canonical_status == canonical_status.PENDING

        # 3. Operator flips the pair LIVE once testing looks right.
        go_live(link, actor=affiliate_user)
        link.refresh_from_db()
        assert link.phase == AffiliateOfferLink.PHASE_LIVE

        # 4. An affiliate configures a postback before the next status lands.
        config = AffiliatePostbackConfig.objects.create(affiliate=affiliate_user, url='https://aff.test/cb')

        # 5. Now a buyer status arrives post-go-live — it's authoritative,
        # and (being applied) fires a postback.
        with patch('leadgen.postback_delivery.deliver_affiliate_postback.delay') as mock_delay:
            buyer_event = apply_status_change(lead, canonical_status.FTD, source=LeadStatusEvent.SOURCE_BUYER)
        assert buyer_event.applied is True
        lead.refresh_from_db()
        assert lead.canonical_status == canonical_status.FTD
        mock_delay.assert_called_once()
        delivery = PostbackDelivery.objects.get(config=config)

        mock_resp = MagicMock(status_code=200)
        mock_resp.raise_for_status.return_value = None
        with patch('leadgen.postback_delivery.validate_postback_url'), \
             patch('leadgen.postback_delivery.requests.post', return_value=mock_resp) as mock_post:
            from leadgen.postback_delivery import deliver_affiliate_postback
            deliver_affiliate_postback(delivery.pk)
        delivery.refresh_from_db()
        assert delivery.status == PostbackDelivery.STATUS_DELIVERED
        assert mock_post.call_args.kwargs['headers']['X-Nexora-Signature'].startswith('sha256=')

        # 6. The affiliate pulls the lead back and sees the whole story —
        # but the timeline only ever shows APPLIED events (LeadDetailOutSerializer
        # deliberately filters out recorded-but-not-applied ones — see
        # serializers.py): the TESTING-phase buyer FTD from earlier must NOT
        # appear, even though the LIVE-phase FTD that came after it does.
        detail = client.get(f'{LIST_URL}/{lead.pk}')
        assert detail.status_code == 200
        assert detail.data['canonical_status'] == canonical_status.FTD
        timeline_to_statuses = [e['to_status'] for e in detail.data['status_timeline']]
        assert timeline_to_statuses.count(canonical_status.PENDING) == 1
        assert timeline_to_statuses.count(canonical_status.FTD) == 1
        # The story now opens at intake: leadgen.delivery_status reports the
        # DELIVERY state into canonical_status too, so `new` is the first
        # applied event rather than the affiliate seeing nothing until the
        # buyer first speaks. The TESTING-phase buyer FTD is still absent —
        # that is what this assertion is really guarding.
        assert timeline_to_statuses == [
            canonical_status.NEW, canonical_status.PENDING, canonical_status.FTD,
        ]
        assert all(e['source'] != 'buyer' or e['to_status'] != canonical_status.FTD
                   or e['lead_seq'] > 1 for e in detail.data['status_timeline'])

        # The list/pull endpoint (with a status filter) surfaces the same
        # canonical_status for reconciliation-style polling.
        list_resp = client.get(LIST_URL, {'status': canonical_status.FTD})
        assert list_resp.status_code == 200
        pulled = next(item for item in list_resp.data['results'] if item['id'] == lead.pk)
        assert pulled['canonical_status'] == canonical_status.FTD

        # The vocabulary endpoint (spec §4.1) lists every canonical status a
        # source might see, so it can localize/display without hand-copying
        # leadgen/canonical_status.py.
        vocab_resp = client.get(STATUSES_URL)
        assert vocab_resp.status_code == 200
        assert canonical_status.FTD in [item['value'] for item in vocab_resp.data]

        # 7. Idempotency still holds end-to-end: resubmitting the same
        # source_id never creates a second lead, even after all of the
        # above.
        resubmit = client.post(SUBMIT_URL, {
            'first_name': 'Accept', 'last_name': 'Ance', 'email': 'accept@test.com',
            'phone': '+15559998888', 'vertical': 'finance', 'source_id': 'acc-flow-1',
            'offer_id': eligible_offer.pk,
        }, format='json')
        assert resubmit.status_code == 200  # existing lead, not created
        assert Lead.objects.filter(source_id='acc-flow-1', affiliate=affiliate_user).count() == 1
