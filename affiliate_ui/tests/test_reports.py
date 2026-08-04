"""Tests for the three affiliate report pages (daily / offer / goal).

The aggregation itself already existed as raw SQL in affiliate/sql/; these
tests pin its behaviour and cover four defects found by reading it:

  1. daily_report ordered by cl.day on a FULL OUTER JOIN, so a day with
     conversions but no clicks (cl.day = NULL) sorted to the top out of order.
  2. CR used integer division, so 2 conversions on 300 clicks read as 0%.
  3. The offer filter dropdown keyed off conversions only, so it was empty for
     any affiliate who had sent traffic but not yet converted.
  4. The views were @login_required only, not @require_approved_affiliate like
     the rest of the portal.

Reports read tracker Click/Conversion, NOT leadgen Lead — see
test_leads_do_not_feed_reports, which pins that boundary deliberately.
"""
from datetime import date, datetime, time, timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.utils import timezone

from affiliate.dao import daily_report, goal_report, offer_report
from offer.models import Advertiser, Goal, Offer
from tracker.models import Click, Conversion
from user_profile.models import Profile

User = get_user_model()

DAILY_URL = '/partner/reports/daily/'
OFFER_URL = '/partner/reports/offer/'
GOAL_URL = '/partner/reports/goal/'
ZERO = Decimal('0.00')


def _reports_brand():
    """Shared brand for these tests' affiliates and offers. The reports offer
    filter is now intersected with offers_for_affiliate (brand-only, no
    unbranded fallback), so both sides must carry a brand."""
    from brands.models import Brand

    return Brand.objects.get_or_create(
        slug='test-brand-reports',
        defaults=dict(name='Reports Test Brand', primary_domain='reports.test',
                      tracking_domain='t.reports.test', is_default=False),
    )[0]


def _affiliate(username, approved=True):
    user = User.objects.create_user(username=username, password='pass')
    user.profile.role = Profile.Role.AFFILIATE
    user.profile.brand = _reports_brand()
    if approved:
        user.profile.affiliate_status = Profile.AffiliateStatus.APPROVED
        user.profile.email_verified = True
    user.profile.save()
    return user


@pytest.fixture
def offer(db):
    adv_user = User.objects.create_user(username='rep_adv', password='pass', email='ra@test.com')
    # Advertiser left at its onboarding default (PENDING/unverified) on
    # purpose: the reports filter uses offers_for_affiliate(historical=True),
    # which keeps the brand rule but drops the availability gate, so an
    # affiliate's own traffic stays filterable regardless of what later
    # happened to the advertiser. If that ever regresses, this fixture is what
    # catches it.
    advertiser = Advertiser.objects.create(user=adv_user, company='RepAdv', email='ra@test.com')
    return Offer.objects.create(
        title='Report Offer', tracking_link='https://t.test/r', advertiser=advertiser,
        brand=_reports_brand())


@pytest.fixture
def other_offer(db, offer):
    return Offer.objects.create(
        title='Other Offer', tracking_link='https://t.test/o', advertiser=offer.advertiser,
        brand=_reports_brand())


@pytest.fixture
def goal(db):
    return Goal.objects.create(name='Signup')


def _click(user, offer, when=None):
    click = Click.objects.create(affiliate=user, offer=offer, ip='127.0.0.1', revenue=ZERO, payout=ZERO)
    if when:
        Click.objects.filter(pk=click.pk).update(created_at=when)
    return click


def _conversion(user, offer, goal, status, payout='25.00', when=None):
    conv = Conversion.objects.create(
        affiliate=user, offer=offer, goal=goal, status=status,
        payout=Decimal(payout), revenue=Decimal('40.00'), ip='127.0.0.1')
    if when:
        Conversion.objects.filter(pk=conv.pk).update(created_at=when)
    return conv


def _range(days=6):
    return (datetime.combine(date.today() - timedelta(days=days), time.min),
            datetime.combine(date.today(), time.max))


@pytest.mark.django_db
class TestDailyReport:
    def test_buckets_and_payouts_per_day(self, offer, goal):
        user = _affiliate('rep_daily')
        today = timezone.now()
        for _ in range(10):
            _click(user, offer, today)
        _conversion(user, offer, goal, 'approved', when=today)
        _conversion(user, offer, goal, 'hold', when=today)
        _conversion(user, offer, goal, 'rejected', when=today)

        start, end = _range()
        rows = daily_report(user.id, start, end, 0)
        assert len(rows) == 1
        row = rows[0]
        assert row['clicks'] == 10
        assert row['total_qty'] == 3
        assert (row['approved_qty'], row['hold_qty'], row['rejected_qty']) == (1, 1, 1)
        assert row['total_payout'] == Decimal('75.00')
        assert row['approved_payout'] == Decimal('25.00')

    def test_conversion_rate_is_not_integer_divided(self, offer, goal):
        """Defect 2: 2 conversions on 300 clicks used to read as 0%."""
        user = _affiliate('rep_cr')
        today = timezone.now()
        for _ in range(300):
            _click(user, offer, today)
        _conversion(user, offer, goal, 'approved', when=today)
        _conversion(user, offer, goal, 'approved', when=today)

        start, end = _range()
        cr = daily_report(user.id, start, end, 0)[0]['cr']
        assert cr > 0, 'conversion rate truncated to zero by integer division'
        assert round(float(cr), 2) == 0.67

    def test_days_sort_newest_first_even_without_clicks(self, offer, goal):
        """Defect 1: a conversion-only day has cl.day = NULL and used to sort
        to the top regardless of its real date."""
        user = _affiliate('rep_order')
        now = timezone.now()
        # 3 days ago: conversions but NO clicks -> the NULL-join row.
        _conversion(user, offer, goal, 'approved', when=now - timedelta(days=3))
        # today and yesterday: clicks present.
        for day_offset in (0, 1):
            _click(user, offer, now - timedelta(days=day_offset))
            _conversion(user, offer, goal, 'approved', when=now - timedelta(days=day_offset))

        start, end = _range()
        dates = [row['date'] for row in daily_report(user.id, start, end, 0)]
        assert dates == sorted(dates, reverse=True), f'rows out of date order: {dates}'

    def test_offer_filter_narrows_results(self, offer, other_offer, goal):
        user = _affiliate('rep_filter')
        today = timezone.now()
        _click(user, offer, today)
        _conversion(user, offer, goal, 'approved', when=today)
        _click(user, other_offer, today)
        _conversion(user, other_offer, goal, 'approved', when=today)

        start, end = _range()
        assert daily_report(user.id, start, end, 0)[0]['total_qty'] == 2
        assert daily_report(user.id, start, end, offer.id)[0]['total_qty'] == 1

    def test_date_range_narrows_results(self, offer, goal):
        user = _affiliate('rep_range')
        now = timezone.now()
        _conversion(user, offer, goal, 'approved', when=now)
        _conversion(user, offer, goal, 'approved', when=now - timedelta(days=20))

        start, end = _range()
        assert sum(r['total_qty'] for r in daily_report(user.id, start, end, 0)) == 1
        wide_start = datetime.combine(date.today() - timedelta(days=30), time.min)
        assert sum(r['total_qty'] for r in daily_report(user.id, wide_start, end, 0)) == 2

    def test_another_affiliates_data_is_never_included(self, offer, goal):
        mine = _affiliate('rep_mine')
        theirs = _affiliate('rep_theirs')
        today = timezone.now()
        _click(theirs, offer, today)
        _conversion(theirs, offer, goal, 'approved', when=today)

        start, end = _range()
        assert daily_report(mine.id, start, end, 0) == []


@pytest.mark.django_db
class TestOfferAndGoalReports:
    def test_offer_report_rows_per_offer(self, offer, other_offer, goal):
        user = _affiliate('rep_offer')
        today = timezone.now()
        for _ in range(4):
            _click(user, offer, today)
        _conversion(user, offer, goal, 'approved', when=today)
        _click(user, other_offer, today)

        start, end = _range()
        rows = {r['offer_title']: r for r in offer_report(user.id, start, end)}
        assert rows['Report Offer']['clicks'] == 4
        assert rows['Report Offer']['total_qty'] == 1
        assert rows['Report Offer']['approved_payout'] == Decimal('25.00')
        assert rows['Other Offer']['total_qty'] == 0

    def test_goal_report_rows_per_goal(self, offer, goal):
        user = _affiliate('rep_goal')
        second_goal = Goal.objects.create(name='Deposit')
        today = timezone.now()
        _conversion(user, offer, goal, 'approved', when=today)
        _conversion(user, offer, second_goal, 'approved', when=today)
        _conversion(user, offer, second_goal, 'hold', when=today)

        start, end = _range()
        rows = {r['goal_name']: r for r in goal_report(user.id, start, end)}
        assert rows['Signup']['total_qty'] == 1
        assert rows['Deposit']['total_qty'] == 2
        assert rows['Deposit']['approved_qty'] == 1
        assert rows['Deposit']['approved_payout'] == Decimal('25.00')

    def test_goal_ownership(self, offer, goal):
        mine = _affiliate('rep_goal_mine')
        theirs = _affiliate('rep_goal_theirs')
        _conversion(theirs, offer, goal, 'approved', when=timezone.now())
        start, end = _range()
        assert goal_report(mine.id, start, end) == []


@pytest.mark.django_db
class TestEarningsReconcileWithPayouts:
    def test_report_approved_payout_matches_payouts_source_of_truth(self, offer, goal):
        """The money column must agree with what Payouts says is owed —
        payouts.services.get_unpaid_earnings is the single source."""
        from payouts.services import get_unpaid_earnings

        user = _affiliate('rep_money')
        today = timezone.now()
        _conversion(user, offer, goal, 'approved', payout='30.00', when=today)
        _conversion(user, offer, goal, 'approved', payout='20.00', when=today)
        _conversion(user, offer, goal, 'hold', payout='99.00', when=today)
        _conversion(user, offer, goal, 'rejected', payout='77.00', when=today)

        start, end = _range()
        reported = sum(r['approved_payout'] for r in daily_report(user.id, start, end, 0))
        owed = get_unpaid_earnings(user, (date.today() - timedelta(days=6)), date.today())

        assert reported == owed == Decimal('50.00'), (
            f'report says {reported}, payouts says {owed} — these must never disagree')


@pytest.mark.django_db
class TestReportPagesAndGating:
    def test_approved_affiliate_sees_pages(self, offer):
        user = _affiliate('rep_page')
        client = Client()
        client.force_login(user)
        for url in (DAILY_URL, OFFER_URL, GOAL_URL):
            assert client.get(url).status_code == 200, url

    def test_pending_affiliate_is_blocked(self, offer):
        """Defect 4: these were @login_required only, so a pending affiliate
        could open them while every other portal page blocked them."""
        pending = _affiliate('rep_pending', approved=False)
        client = Client()
        client.force_login(pending)
        for url in (DAILY_URL, OFFER_URL, GOAL_URL):
            assert client.get(url).status_code == 403, url

    def test_anonymous_is_redirected(self):
        client = Client()
        for url in (DAILY_URL, OFFER_URL, GOAL_URL):
            assert client.get(url).status_code == 302, url

    def test_empty_range_shows_the_empty_state_not_an_error(self, offer):
        user = _affiliate('rep_empty')
        client = Client()
        client.force_login(user)
        for url in (DAILY_URL, OFFER_URL, GOAL_URL):
            response = client.get(url)
            assert response.status_code == 200
            body = response.content.decode()
            assert 'Nothing to report yet' in body, url
            assert 'No data found for the selected criteria' not in body, url

    def test_offer_filter_lists_offers_with_clicks_only(self, offer):
        """Defect 3: the dropdown keyed off conversions, so an affiliate with
        traffic but no conversions yet saw an empty filter."""
        user = _affiliate('rep_dropdown')
        _click(user, offer, timezone.now())
        client = Client()
        client.force_login(user)
        assert 'Report Offer' in client.get(DAILY_URL).content.decode()

    def test_populated_report_renders_rows(self, offer, goal):
        user = _affiliate('rep_rows')
        today = timezone.now()
        _click(user, offer, today)
        _conversion(user, offer, goal, 'approved', when=today)
        client = Client()
        client.force_login(user)
        body = client.get(DAILY_URL).content.decode()
        assert 'Nothing to report yet' not in body
        assert '25.00' in body


@pytest.mark.django_db
class TestReportDataSourceBoundary:
    def test_leads_do_not_feed_reports(self, offer):
        """Pinned deliberately, not an oversight: reports aggregate tracker
        Click/Conversion, while the leadgen inbound API writes Lead /
        LeadStatusEvent. Nothing bridges the two today, so an affiliate who
        only submits leads sees empty reports. If a lead→conversion bridge is
        ever built, this test should fail and be rewritten."""
        from leadgen.models import Lead, LeadStatusEvent
        from leadgen.status_sync import apply_status_change

        user = _affiliate('rep_boundary')
        lead = Lead.objects.create(
            intake_channel=Lead.CHANNEL_AFFILIATE_API, affiliate=user, offer=offer,
            email='b@test.com', phone='+15551234567')
        apply_status_change(lead, 'ftd', source=LeadStatusEvent.SOURCE_OPERATOR)

        start, end = _range()
        assert daily_report(user.id, start, end, 0) == []
        assert offer_report(user.id, start, end) == []
        assert goal_report(user.id, start, end) == []
