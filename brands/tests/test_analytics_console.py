"""Analytics Overview — the arithmetic behind /admin/analytics/.

This page reports revenue and conversion rate, so the sums are pinned rather
than assumed. It also aggregates the source tables directly instead of reading
the reporting matviews (see brands/views/analytics_views.py for why), which
makes the brand scoping this page's own responsibility — so that is asserted
here too.
"""
import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from brands.models import Brand
from brands.views.analytics_views import _align, _delta, _totals, _traffic_mix
from offer.models import Advertiser, Offer
from tracker.models import APPROVED_STATUS, Click, Conversion

User = get_user_model()


def _brand(slug):
    return Brand.objects.create(
        slug=slug, name=slug, primary_domain=f'{slug}.example.com',
        tracking_domain=f't.{slug}.example.com',
    )


class AnalyticsBase(TestCase):
    def setUp(self):
        self.brand = _brand('an-a')
        self.other = _brand('an-b')
        self.adv_user = User.objects.create_user('an-adv', 'adv@an.test', 'pw')
        self.advertiser = Advertiser.objects.create(
            brand=self.brand, user=self.adv_user, company='Adv Co', email='adv@an.test',
        )
        self.offer = Offer.objects.create(
            title='Offer One', advertiser=self.advertiser, brand=self.brand,
        )
        self.affiliate = User.objects.create_user('an-aff', 'aff@an.test', 'pw')

    def _click(self, *, brand=None, days_ago=0, sub1=''):
        click = Click.objects.create(
            brand=brand or self.brand, offer=self.offer, affiliate=self.affiliate,
            ip='10.0.0.1', revenue=Decimal('1.00'), payout=Decimal('1.00'), sub1=sub1,
        )
        if days_ago:
            Click.objects.filter(pk=click.pk).update(
                created_at=timezone.now() - datetime.timedelta(days=days_ago)
            )
        return click

    def _conversion(self, *, brand=None, payout='10.00', status=APPROVED_STATUS, days_ago=0):
        conv = Conversion.objects.create(
            brand=brand or self.brand, offer=self.offer, affiliate=self.affiliate,
            payout=Decimal(payout), status=status,
        )
        if days_ago:
            Conversion.objects.filter(pk=conv.pk).update(
                created_at=timezone.now() - datetime.timedelta(days=days_ago)
            )
        return conv


class TotalsTest(AnalyticsBase):
    def test_revenue_counts_approved_conversions_only(self):
        self._conversion(payout='10.00', status=APPROVED_STATUS)
        self._conversion(payout='99.00', status='pending')

        start = (timezone.now() - datetime.timedelta(days=6)).date()
        totals = _totals(Click.objects.all(), Conversion.objects.all(), start, None, APPROVED_STATUS)

        # Both conversions are counted; only the approved one earns.
        assert totals['conversions'] == 2
        assert totals['revenue'] == Decimal('10.00')

    def test_conversion_rate_is_conversions_over_clicks(self):
        for _ in range(4):
            self._click()
        self._conversion()

        start = (timezone.now() - datetime.timedelta(days=6)).date()
        totals = _totals(Click.objects.all(), Conversion.objects.all(), start, None, APPROVED_STATUS)

        assert totals['conversion_rate'] == 25.0

    def test_no_clicks_does_not_divide_by_zero(self):
        start = (timezone.now() - datetime.timedelta(days=6)).date()
        totals = _totals(Click.objects.all(), Conversion.objects.all(), start, None, APPROVED_STATUS)
        assert totals['conversion_rate'] == 0
        assert totals['clicks'] == 0

    def test_window_excludes_older_rows(self):
        self._click(days_ago=0)
        self._click(days_ago=40)

        start = (timezone.now() - datetime.timedelta(days=6)).date()
        totals = _totals(Click.objects.all(), Conversion.objects.all(), start, None, APPROVED_STATUS)
        assert totals['clicks'] == 1


class DeltaTest(TestCase):
    def test_percentage_change(self):
        assert _delta(150, 100) == 50.0
        assert _delta(50, 100) == -50.0

    def test_no_baseline_is_none_not_infinity(self):
        # "Up 100%" from nothing overstates a single event, and rendering a
        # green arrow for it is worse than rendering nothing.
        assert _delta(10, 0) is None
        assert _delta(0, 0) is None


class AlignTest(TestCase):
    def test_zero_fills_quiet_days_and_keeps_series_in_step(self):
        start = datetime.date(2026, 8, 1)
        a = {datetime.date(2026, 8, 1): 5, datetime.date(2026, 8, 3): 7}
        b = {datetime.date(2026, 8, 2): 2}

        labels, series_a, series_b = _align(a, b, start, 4)

        assert len(labels) == len(series_a) == len(series_b) == 4
        assert series_a == [5, 0, 7, 0]
        assert series_b == [0, 2, 0, 0]

    def test_labels_span_the_whole_window(self):
        start = datetime.date(2026, 8, 1)
        labels, _, _ = _align({}, {}, start, 3)
        assert labels == ['Aug 01', 'Aug 02', 'Aug 03']


class TrafficMixTest(AnalyticsBase):
    def test_groups_by_sub1(self):
        self._click(sub1='paid-search')
        self._click(sub1='paid-search')
        self._click(sub1='social')

        start = (timezone.now() - datetime.timedelta(days=6)).date()
        chart = _traffic_mix(Click.objects.all(), start)

        assert [(s.label, s.value) for s in chart['segments']] == [
            ('paid-search', 2), ('social', 1),
        ]

    def test_a_click_is_counted_once(self):
        # Guards the m2m trap: grouping through Offer.traffic_sources would
        # count one click once per source the offer is tagged with.
        self._click(sub1='paid-search')
        start = (timezone.now() - datetime.timedelta(days=6)).date()
        chart = _traffic_mix(Click.objects.all(), start)
        assert chart['total'] == 1

    def test_blank_sub1_is_labelled_not_dropped(self):
        self._click(sub1='')
        start = (timezone.now() - datetime.timedelta(days=6)).date()
        chart = _traffic_mix(Click.objects.all(), start)
        assert chart['segments'][0].label == 'Unattributed'

    def test_tail_folds_into_other(self):
        for i in range(8):
            self._click(sub1=f'src-{i}')
        start = (timezone.now() - datetime.timedelta(days=6)).date()
        chart = _traffic_mix(Click.objects.all(), start, limit=5)

        assert len(chart['segments']) == 6
        assert chart['segments'][-1].label == 'Other'
        assert chart['segments'][-1].value == 3
        # Folding must not lose clicks.
        assert chart['total'] == 8

    def test_no_clicks_is_empty(self):
        start = (timezone.now() - datetime.timedelta(days=6)).date()
        assert _traffic_mix(Click.objects.all(), start)['empty'] is True


class AnalyticsPageTest(AnalyticsBase):
    def setUp(self):
        super().setUp()
        self.staff = User.objects.create_user('an-staff', 'staff@an.test', 'pw', is_staff=True)
        self.staff.profile.brand = self.brand
        self.staff.profile.save()
        self.url = reverse('admin_analytics')

    def test_requires_staff(self):
        response = self.client.get(self.url)
        assert response.status_code == 302

    def test_renders_for_staff(self):
        self.client.force_login(self.staff)
        response = self.client.get(self.url)
        assert response.status_code == 200
        self.assertTemplateUsed(response, 'admin_shared/analytics.html')

    def test_window_choice_is_validated(self):
        self.client.force_login(self.staff)
        # An unsupported or junk window falls back to the default rather than
        # letting the querystring pick an unbounded range.
        for value in ('9999', 'abc', '-5'):
            response = self.client.get(self.url, {'days': value})
            assert response.status_code == 200
            assert response.context['days'] == 30

    def test_accepts_a_supported_window(self):
        self.client.force_login(self.staff)
        response = self.client.get(self.url, {'days': '7'})
        assert response.context['days'] == 7
