"""Tests for conversion-level fraud rules."""
from fraud.conversion_rules import (
    r_conversion_velocity,
    r_payout_anomaly,
    r_short_click_to_conversion,
    score_conversion,
)


class TestRShortC2C:
    def test_fires_under_min_seconds(self):
        delta, tag = r_short_click_to_conversion({'click_to_conversion_seconds': 2})
        assert delta == 50
        assert '2s' in tag

    def test_fires_at_zero(self):
        delta, tag = r_short_click_to_conversion({'click_to_conversion_seconds': 0})
        assert delta == 50

    def test_no_fire_at_exactly_min(self):
        delta, _ = r_short_click_to_conversion({'click_to_conversion_seconds': 5})
        assert delta == 0

    def test_no_fire_when_seconds_none(self):
        delta, _ = r_short_click_to_conversion({'click_to_conversion_seconds': None})
        assert delta == 0

    def test_custom_min_seconds(self):
        delta, _ = r_short_click_to_conversion(
            {'click_to_conversion_seconds': 9, 'min_click_seconds': 10},
        )
        assert delta == 50


class TestRConversionVelocity:
    def test_fires_above_threshold(self):
        delta, tag = r_conversion_velocity({'conversion_velocity': 11})
        assert delta == 40
        assert '11' in tag

    def test_no_fire_at_threshold(self):
        delta, _ = r_conversion_velocity({'conversion_velocity': 10})
        assert delta == 0

    def test_custom_threshold(self):
        delta, _ = r_conversion_velocity(
            {'conversion_velocity': 6, 'conversion_velocity_threshold': 5},
        )
        assert delta == 40


class TestRPayoutAnomaly:
    def test_fires_when_payout_too_high(self):
        delta, tag = r_payout_anomaly({'payout': 100.0, 'avg_payout': 10.0})
        assert delta == 35
        assert '100.00' in tag

    def test_no_fire_within_multiplier(self):
        delta, _ = r_payout_anomaly({'payout': 25.0, 'avg_payout': 10.0})
        assert delta == 0

    def test_no_fire_when_avg_zero(self):
        delta, _ = r_payout_anomaly({'payout': 999.0, 'avg_payout': 0})
        assert delta == 0


class TestScoreConversion:
    def test_all_rules_fire_together(self):
        ctx = {
            'click_to_conversion_seconds': 1,
            'conversion_velocity': 20,
            'payout': 200.0,
            'avg_payout': 10.0,
        }
        score, reasons = score_conversion(ctx)
        # short_c2c=50 + conv_velocity=40 + payout_anomaly=35
        assert score == 125
        assert len(reasons) == 3

    def test_clean_conversion_scores_zero(self):
        ctx = {
            'click_to_conversion_seconds': 120,
            'conversion_velocity': 2,
            'payout': 10.0,
            'avg_payout': 10.0,
        }
        score, reasons = score_conversion(ctx)
        assert score == 0
        assert reasons == []
