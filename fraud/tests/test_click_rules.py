"""Tests for click-level fraud rules — each rule must fire on a matching context."""
from fraud.rules import (
    r_bot_ua,
    r_click_flood,
    r_impossible_geo,
    r_no_referrer,
    r_repeat_click,
    score_click,
)


class TestRBotUa:
    def test_fires_on_known_bot_fragment(self):
        delta, tag = r_bot_ua({'ua': 'Mozilla/5.0 Googlebot/2.1'})
        assert delta == 80
        assert tag.startswith('bot_ua:')

    def test_fires_on_headless_chrome(self):
        delta, tag = r_bot_ua({'ua': 'HeadlessChrome/120.0'})
        assert delta == 80

    def test_fires_on_python_requests(self):
        delta, tag = r_bot_ua({'ua': 'python-requests/2.31'})
        assert delta == 80

    def test_fires_on_empty_ua(self):
        delta, tag = r_bot_ua({'ua': ''})
        assert delta == 80
        assert tag == 'bot_ua:empty'

    def test_no_fire_on_normal_browser(self):
        ua = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36'
        delta, tag = r_bot_ua({'ua': ua})
        assert delta == 0
        assert tag is None


class TestRNoReferrer:
    def test_fires_when_referrer_absent(self):
        delta, tag = r_no_referrer({'referrer': ''})
        assert delta == 20
        assert tag == 'no_referrer'

    def test_fires_when_referrer_none(self):
        delta, _ = r_no_referrer({})
        assert delta == 20

    def test_no_fire_when_referrer_present(self):
        delta, tag = r_no_referrer({'referrer': 'https://example.com'})
        assert delta == 0
        assert tag is None


class TestRClickFlood:
    def test_fires_above_threshold(self):
        delta, tag = r_click_flood({'click_flood_count': 31})
        assert delta == 60
        assert '31' in tag

    def test_no_fire_at_threshold(self):
        delta, _ = r_click_flood({'click_flood_count': 30})
        assert delta == 0

    def test_no_fire_below_threshold(self):
        delta, _ = r_click_flood({'click_flood_count': 5})
        assert delta == 0

    def test_custom_threshold(self):
        delta, _ = r_click_flood({'click_flood_count': 11, 'click_flood_threshold': 10})
        assert delta == 60


class TestRImpossibleGeo:
    def test_fires_when_country_not_in_offer_countries(self):
        delta, tag = r_impossible_geo({'country': 'DE', 'offer_countries': ['US', 'GB']})
        assert delta == 30
        assert 'DE' in tag

    def test_no_fire_when_country_in_offer_countries(self):
        delta, _ = r_impossible_geo({'country': 'US', 'offer_countries': ['US', 'GB']})
        assert delta == 0

    def test_no_fire_when_offer_countries_empty(self):
        delta, _ = r_impossible_geo({'country': 'DE', 'offer_countries': []})
        assert delta == 0

    def test_no_fire_when_visitor_country_empty(self):
        delta, _ = r_impossible_geo({'country': '', 'offer_countries': ['US']})
        assert delta == 0


class TestRRepeatClick:
    def test_fires_when_repeat(self):
        delta, tag = r_repeat_click({'repeat_click': True})
        assert delta == 25
        assert tag == 'repeat_click'

    def test_no_fire_when_not_repeat(self):
        delta, tag = r_repeat_click({'repeat_click': False})
        assert delta == 0
        assert tag is None


class TestScoreClick:
    def test_accumulates_multiple_rules(self):
        ctx = {
            'ua': 'Googlebot/2.1',
            'referrer': '',
            'click_flood_count': 50,
            'country': 'CN',
            'offer_countries': ['US'],
            'repeat_click': True,
        }
        score, reasons = score_click(ctx)
        # bot_ua=80 + no_referrer=20 + click_flood=60 + impossible_geo=30 + repeat_click=25
        assert score == 215
        assert len(reasons) == 5

    def test_clean_click_scores_zero(self):
        ctx = {
            'ua': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0',
            'referrer': 'https://google.com',
            'click_flood_count': 1,
            'country': 'US',
            'offer_countries': ['US'],
            'repeat_click': False,
        }
        score, reasons = score_click(ctx)
        assert score == 0
        assert reasons == []
