"""The derived numbers on the Buyers and Routing Rules consoles.

These panels report on money-adjacent delivery behaviour, so the arithmetic is
pinned rather than eyeballed: an accept rate that silently counts undelivered
rows, or a latency that averages in rows that never arrived, would read as a
healthy buyer while the opposite is true.

Brand scoping is asserted here too. LeadInjection carries no brand of its own —
it is scoped through ``lead__brand`` — which is exactly the kind of indirect
join that leaks across tenants when nobody tests it.
"""
import datetime

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from brands.models import Brand
from leadgen.admin_views import _buyer_health, _delivery_latency, _routing_stats
from leadgen.models import BoxType, Lead, LeadBuyer, LeadInjection

User = get_user_model()


def _brand(slug):
    return Brand.objects.create(
        slug=slug, name=slug, primary_domain=f'{slug}.example.com',
        tracking_domain=f't.{slug}.example.com',
    )


class ConsoleStatsBase(TestCase):
    def setUp(self):
        self.brand = _brand('stats-a')
        self.other = _brand('stats-b')
        self.box_type = BoxType.objects.create(
            name='Stats Box', slug='stats-box',
            connector_class='leadgen.connectors.LeadBuyerConnector',
            auth_type=BoxType.AUTH_API_KEY_QUERY, auth_param_name='apiKey',
            single_endpoint_path='/leads', batch_endpoint_path='',
            fetch_endpoint_path='/leads', batch_max_size=1,
            rate_limit_burst=10, rate_limit_refill_tokens=1, rate_limit_refill_seconds=1,
        )
        self.buyer = LeadBuyer.objects.create(
            brand=self.brand, box_type=self.box_type, name='Primary', slug='stats-primary',
            is_active=True, base_url='https://primary.test',
        )
        self.backup = LeadBuyer.objects.create(
            brand=self.brand, box_type=self.box_type, name='Backup', slug='stats-backup',
            is_active=True, base_url='https://backup.test',
        )

    def _lead(self, brand=None, **kwargs):
        return Lead.objects.create(
            intake_channel=Lead.CHANNEL_LANDING_PAGE,
            brand=brand or self.brand,
            email=f'lead{Lead.objects.count()}@test.com',
            phone='+15550000000',
            **kwargs,
        )

    def _injection(self, lead, buyer=None, *, status, latency_ms=None):
        inj = LeadInjection.objects.create(
            lead=lead, buyer=buyer or self.buyer, status=status,
        )
        if latency_ms is not None:
            inj.delivered_at = inj.created_at + datetime.timedelta(milliseconds=latency_ms)
            inj.save(update_fields=['delivered_at'])
        return inj


class DeliveryLatencyTest(ConsoleStatsBase):
    def test_averages_only_delivered_rows(self):
        lead = self._lead()
        self._injection(lead, status=LeadInjection.STATUS_DELIVERED, latency_ms=100)
        self._injection(lead, status=LeadInjection.STATUS_DELIVERED, latency_ms=300)
        # A row that never arrived has no latency. Counting it as zero would
        # halve the average and flatter a failing buyer.
        self._injection(lead, status=LeadInjection.STATUS_FAILED)

        assert _delivery_latency(LeadInjection.objects.all()) == 200

    def test_returns_none_when_nothing_delivered(self):
        lead = self._lead()
        self._injection(lead, status=LeadInjection.STATUS_FAILED)
        assert _delivery_latency(LeadInjection.objects.all()) is None


class BuyerHealthTest(ConsoleStatsBase):
    def test_accept_rate_counts_delivered_over_all_attempts(self):
        lead = self._lead()
        self._injection(lead, status=LeadInjection.STATUS_DELIVERED, latency_ms=50)
        self._injection(lead, status=LeadInjection.STATUS_DELIVERED, latency_ms=50)
        self._injection(lead, status=LeadInjection.STATUS_FAILED)
        self._injection(lead, status=LeadInjection.STATUS_DUPLICATE)

        health = _buyer_health(self.brand, show_all_brands=False)

        assert health['total'] == 4
        assert health['delivered'] == 2
        assert health['accept_rate']['pct'] == 50.0

    def test_outcome_ring_labels_every_band(self):
        lead = self._lead()
        self._injection(lead, status=LeadInjection.STATUS_DELIVERED, latency_ms=10)
        health = _buyer_health(self.brand, show_all_brands=False)
        assert [s.label for s in health['outcomes']['segments']] == [
            'Delivered', 'Pending', 'Duplicate', 'Failed',
        ]

    def test_scoped_to_the_operators_brand(self):
        # Injection has no brand column — it scopes through lead__brand.
        mine = self._lead()
        theirs = self._lead(brand=self.other)
        self._injection(mine, status=LeadInjection.STATUS_DELIVERED, latency_ms=10)
        self._injection(theirs, status=LeadInjection.STATUS_DELIVERED, latency_ms=10)

        assert _buyer_health(self.brand, show_all_brands=False)['total'] == 1
        assert _buyer_health(self.brand, show_all_brands=True)['total'] == 2

    def test_ignores_rows_outside_the_window(self):
        lead = self._lead()
        old = self._injection(lead, status=LeadInjection.STATUS_DELIVERED, latency_ms=10)
        LeadInjection.objects.filter(pk=old.pk).update(
            created_at=timezone.now() - datetime.timedelta(days=3)
        )
        assert _buyer_health(self.brand, show_all_brands=False)['total'] == 0

    def test_empty_window_does_not_divide_by_zero(self):
        health = _buyer_health(self.brand, show_all_brands=False)
        assert health['total'] == 0
        assert health['accept_rate']['pct'] == 0.0
        assert health['outcomes']['empty'] is True


class RoutingStatsTest(ConsoleStatsBase):
    def test_matched_counts_leads_that_reached_a_buyer(self):
        reached = self._lead()
        self._injection(reached, status=LeadInjection.STATUS_DELIVERED, latency_ms=20)
        self._lead()  # never routed anywhere

        stats = _routing_stats(self.brand, show_all_brands=False)

        assert stats['matched_text'] == '1 / 2'
        assert stats['matched']['pct'] == 50.0

    def test_a_lead_with_several_attempts_is_matched_once(self):
        lead = self._lead()
        self._injection(lead, self.buyer, status=LeadInjection.STATUS_FAILED)
        self._injection(lead, self.backup, status=LeadInjection.STATUS_DELIVERED, latency_ms=20)

        stats = _routing_stats(self.brand, show_all_brands=False)

        # One lead, matched — not two, which is what a missing .distinct()
        # would report and would let "matched" exceed the lead count.
        assert stats['matched_text'] == '1 / 1'
        assert stats['matched']['pct'] == 100.0

    def test_fallback_is_a_lead_that_needed_more_than_one_buyer(self):
        straight = self._lead()
        self._injection(straight, status=LeadInjection.STATUS_DELIVERED, latency_ms=20)

        waterfall = self._lead()
        self._injection(waterfall, self.buyer, status=LeadInjection.STATUS_FAILED)
        self._injection(waterfall, self.backup, status=LeadInjection.STATUS_DELIVERED, latency_ms=20)

        assert _routing_stats(self.brand, show_all_brands=False)['fallbacks'] == 1

    def test_distributed_counts_delivered_attempts_only(self):
        lead = self._lead()
        self._injection(lead, status=LeadInjection.STATUS_DELIVERED, latency_ms=20)
        self._injection(lead, status=LeadInjection.STATUS_FAILED)

        assert _routing_stats(self.brand, show_all_brands=False)['distributed'] == 1

    def test_by_buyer_bars_are_labelled_with_buyer_names(self):
        lead = self._lead()
        self._injection(lead, self.buyer, status=LeadInjection.STATUS_DELIVERED, latency_ms=20)
        self._injection(lead, self.backup, status=LeadInjection.STATUS_DELIVERED, latency_ms=20)

        labels = {b['label'] for b in _routing_stats(self.brand, show_all_brands=False)['by_buyer']['bars']}
        assert labels == {'Primary', 'Backup'}

    def test_no_activity_is_empty_not_an_error(self):
        stats = _routing_stats(self.brand, show_all_brands=False)
        assert stats['distributed'] == 0
        assert stats['fallbacks'] == 0
        assert stats['latency_ms'] is None
        assert stats['by_buyer']['empty'] is True
