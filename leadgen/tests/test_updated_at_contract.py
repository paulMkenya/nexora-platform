"""Lead.updated_at must move whenever a lead's state changes.

This is the contract `GET /api/leads?updated_since=...` sells: spec §5.2's
pull/reconcile path, the documented safety net for when a postback delivery
to an affiliate fails. If updated_at doesn't move, that endpoint silently
returns an empty page and the affiliate concludes nothing happened — worst
of all for a conversion to FTD, the one event they most need to reconcile.

It was broken exactly this way: every lead mutation in this app uses
QuerySet.update(), and Django applies `auto_now` in Model.save(), not in
update(). updated_at was therefore a second created_at. LeadQuerySet.touch()
is the fix; these tests stop it regressing, per mutation path.
"""
import pytest
from django.utils import timezone

from leadgen import canonical_status
from leadgen.models import Lead, LeadInjection, LeadStatusEvent
from leadgen.status_sync import apply_status_change


def _lead(brand, affiliate_user, offer, **kwargs):
    defaults = dict(
        brand=brand, affiliate=affiliate_user, offer=offer,
        intake_channel=Lead.CHANNEL_AFFILIATE_API,
        email='ua@test.com', phone='+15551234567')
    defaults.update(kwargs)
    return Lead.objects.create(**defaults)


def _stamp(lead):
    return Lead.objects.get(pk=lead.pk).updated_at


@pytest.mark.django_db
class TestUpdatedAtMovesOnStateChange:
    def test_canonical_status_change_bumps_updated_at(self, brand, affiliate_user, offer):
        """The one that matters most: an FTD conversion must be pullable."""
        lead = _lead(brand, affiliate_user, offer)
        before = _stamp(lead)

        apply_status_change(lead, canonical_status.FTD, source=LeadStatusEvent.SOURCE_OPERATOR)

        assert _stamp(lead) > before
        assert Lead.objects.get(pk=lead.pk).canonical_status == canonical_status.FTD

    def test_delivery_status_change_bumps_updated_at(self, brand, affiliate_user, offer):
        lead = _lead(brand, affiliate_user, offer)
        before = _stamp(lead)
        Lead.objects.filter(pk=lead.pk).touch(status=Lead.STATUS_INJECTED)
        assert _stamp(lead) > before

    def test_deposit_flag_bumps_updated_at(self, brand, affiliate_user, offer):
        """What sync_buyer_statuses writes when a buyer reports a deposit."""
        lead = _lead(brand, affiliate_user, offer)
        before = _stamp(lead)
        Lead.objects.filter(pk=lead.pk).touch(
            deposit=True, status=Lead.STATUS_DEPOSIT,
            buyer_status='Deposit', buyer_status_updated_at=timezone.now())
        assert _stamp(lead) > before

    def test_touch_still_writes_the_fields_it_was_given(self, brand, affiliate_user, offer):
        lead = _lead(brand, affiliate_user, offer)
        Lead.objects.filter(pk=lead.pk).touch(status=Lead.STATUS_DUPLICATE)
        assert Lead.objects.get(pk=lead.pk).status == Lead.STATUS_DUPLICATE

    def test_touch_respects_the_queryset_filter(self, brand, affiliate_user, offer):
        """The country backfills are conditional (country_iso2='') — touch
        must not widen what update() would have matched."""
        lead = _lead(brand, affiliate_user, offer, country_iso2='KE')
        before = _stamp(lead)
        matched = Lead.objects.filter(pk=lead.pk, country_iso2='').touch(country_iso2='US')
        assert matched == 0
        assert Lead.objects.get(pk=lead.pk).country_iso2 == 'KE'
        assert _stamp(lead) == before


@pytest.mark.django_db
class TestPullApiSeesTheChange:
    def test_updated_since_returns_a_lead_whose_status_changed(
            self, brand, affiliate_user, affiliate_api_key, offer):
        """End-to-end proof through the actual endpoint: the integrator's
        reconcile loop (poll updated_since, look for FTD) must find it."""
        from rest_framework.test import APIClient

        lead = _lead(brand, affiliate_user, offer)
        cutoff = timezone.now()

        apply_status_change(lead, canonical_status.FTD, source=LeadStatusEvent.SOURCE_OPERATOR)

        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f'ApiKey {affiliate_api_key.secret}')
        resp = client.get('/api/leads', {'updated_since': cutoff.isoformat()})

        assert resp.status_code == 200
        ids = [row['id'] for row in resp.data['results']]
        assert lead.pk in ids, 'a lead that converted to FTD was not returned by updated_since'
        row = next(r for r in resp.data['results'] if r['id'] == lead.pk)
        assert row['canonical_status'] == canonical_status.FTD

    def test_status_filter_returns_ftd_leads(self, brand, affiliate_user, affiliate_api_key, offer):
        """?status=ftd — the documented way to pull conversions."""
        from rest_framework.test import APIClient

        converted = _lead(brand, affiliate_user, offer, email='conv@test.com')
        _lead(brand, affiliate_user, offer, email='plain@test.com', phone='+15559998888')
        apply_status_change(converted, canonical_status.FTD, source=LeadStatusEvent.SOURCE_OPERATOR)

        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f'ApiKey {affiliate_api_key.secret}')
        resp = client.get('/api/leads', {'status': canonical_status.FTD})

        assert resp.status_code == 200
        assert [r['id'] for r in resp.data['results']] == [converted.pk]

    def test_pagination_envelope_shape(self, brand, affiliate_user, affiliate_api_key, offer):
        """count/next/previous/results + page & page_size, as documented."""
        from rest_framework.test import APIClient

        for i in range(3):
            _lead(brand, affiliate_user, offer, email=f'p{i}@test.com', phone=f'+1555000{i:04d}')

        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f'ApiKey {affiliate_api_key.secret}')
        resp = client.get('/api/leads', {'page_size': 2, 'page': 1})

        assert resp.status_code == 200
        assert set(resp.data) >= {'count', 'next', 'previous', 'results'}
        assert resp.data['count'] == 3
        assert len(resp.data['results']) == 2
        assert resp.data['next'] is not None

    def test_deposit_flag_is_exposed_in_the_pull_payload(
            self, brand, affiliate_user, affiliate_api_key, offer):
        from rest_framework.test import APIClient

        lead = _lead(brand, affiliate_user, offer)
        Lead.objects.filter(pk=lead.pk).touch(deposit=True, buyer_status='Deposit')

        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f'ApiKey {affiliate_api_key.secret}')
        resp = client.get('/api/leads', {'ids': str(lead.pk)})

        row = resp.data['results'][0]
        assert row['deposit'] is True
        assert row['buyer_status'] == 'Deposit'


@pytest.mark.django_db
def test_injection_delivery_bumps_updated_at(brand, affiliate_user, offer, buyer):
    """The delivery path writes through touch() too, so a lead that reaches
    a buyer becomes visible to a reconcile poll."""
    lead = _lead(brand, affiliate_user, offer)
    before = _stamp(lead)
    LeadInjection.objects.create(lead=lead, buyer=buyer)
    Lead.objects.filter(pk=lead.pk).touch(status=Lead.STATUS_INJECTED)
    assert _stamp(lead) > before
