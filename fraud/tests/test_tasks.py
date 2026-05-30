"""Integration tests for fraud Celery tasks — seeds real DB rows."""
import uuid
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
import datetime

from tracker.models import Click, Conversion, HOLD_STATUS, REJECTED_STATUS
from offer.models import Offer

User = get_user_model()


def _make_user(**kwargs):
    defaults = dict(username=f'u{uuid.uuid4().hex[:6]}', password='x')
    defaults.update(kwargs)
    return User.objects.create_user(**defaults)


def _make_offer(**kwargs):
    defaults = dict(title='Test Offer', tracking_link='http://example.com')
    defaults.update(kwargs)
    return Offer.objects.create(**defaults)


def _make_click(ip='1.2.3.4', ua='', offer=None, affiliate=None, **kwargs):
    offer = offer or _make_offer()
    affiliate = affiliate or _make_user()
    return Click.objects.create(
        ip=ip,
        ua=ua,
        offer=offer,
        affiliate=affiliate,
        revenue=Decimal('0'),
        payout=Decimal('0'),
        **kwargs,
    )


class TestScoreClickFraud(TestCase):

    @mock.patch('fraud.tasks._flood_count', return_value=0)
    @mock.patch('fraud.tasks._repeat_click', return_value=False)
    @mock.patch('fraud.ipqs.lookup', return_value=None)
    def test_bot_ua_sets_high_score(self, _ipqs, _rep, _flood):
        from fraud.tasks import score_click_fraud
        click = _make_click(ua='python-requests/2.31')
        score_click_fraud(str(click.id))
        click.refresh_from_db()
        assert click.fraud_score >= 80
        assert click.is_bot is True
        assert any('bot_ua' in r for r in click.fraud_reasons)

    @mock.patch('fraud.tasks._flood_count', return_value=50)
    @mock.patch('fraud.tasks._repeat_click', return_value=False)
    @mock.patch('fraud.ipqs.lookup', return_value=None)
    def test_click_flood_adds_score(self, _ipqs, _rep, _flood):
        from fraud.tasks import score_click_fraud
        click = _make_click(ua='Mozilla/5.0 Chrome/120')
        score_click_fraud(str(click.id))
        click.refresh_from_db()
        assert click.fraud_score >= 60
        assert any('click_flood' in r for r in click.fraud_reasons)

    @mock.patch('fraud.tasks._flood_count', return_value=0)
    @mock.patch('fraud.tasks._repeat_click', return_value=True)
    @mock.patch('fraud.ipqs.lookup', return_value=None)
    def test_repeat_click_adds_score(self, _ipqs, _rep, _flood):
        from fraud.tasks import score_click_fraud
        click = _make_click(ua='Mozilla/5.0 Chrome/120')
        score_click_fraud(str(click.id))
        click.refresh_from_db()
        assert any('repeat_click' in r for r in click.fraud_reasons)

    @mock.patch('fraud.tasks._flood_count', return_value=0)
    @mock.patch('fraud.tasks._repeat_click', return_value=False)
    @mock.patch('fraud.ipqs.lookup', return_value=None)
    def test_nonexistent_click_does_not_raise(self, _ipqs, _rep, _flood):
        from fraud.tasks import score_click_fraud
        result = score_click_fraud(str(uuid.uuid4()))
        assert result is None


class TestScoreConversionFraud(TestCase):

    def _make_conversion(self, payout=Decimal('10'), c2c_secs=120):
        offer = _make_offer()
        affiliate = _make_user()
        click_time = timezone.now() - datetime.timedelta(seconds=c2c_secs)
        click = Click.objects.create(
            ip='2.3.4.5', ua='Mozilla/5.0', offer=offer, affiliate=affiliate,
            revenue=Decimal('0'), payout=Decimal('0'),
        )
        # Backdate click to simulate c2c gap
        Click.objects.filter(pk=click.id).update(created_at=click_time)
        return Conversion.objects.create(
            click_id=click.id,
            click_date=click_time,
            offer=offer,
            affiliate=affiliate,
            payout=payout,
            revenue=payout,
            status=HOLD_STATUS,
            goal_value='1',
        )

    def test_short_c2c_fires(self):
        from fraud.tasks import score_conversion_fraud
        conv = self._make_conversion(c2c_secs=2)
        score_conversion_fraud(str(conv.id))
        conv.refresh_from_db()
        assert any('short_c2c' in r for r in conv.fraud_reasons)
        assert conv.fraud_score >= 50

    def test_auto_reject_above_threshold(self):
        from fraud.tasks import score_conversion_fraud
        from django.test import override_settings
        conv = self._make_conversion(c2c_secs=1)
        with override_settings(FRAUD_AUTO_REJECT_AT=40):
            score_conversion_fraud(str(conv.id))
        conv.refresh_from_db()
        assert conv.status == REJECTED_STATUS
        assert conv.auto_rejected_reason != ''
