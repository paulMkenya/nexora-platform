"""
Click-level fraud rules — all pure functions.

Each rule takes a context dict and returns (score_delta, reason_tag) or (0, None).
Context keys available:
  ua, ip, country, offer_country, click_flood_count, existing_click_ids (set)
"""
from typing import Optional, Tuple

# Known bot/crawler user-agent fragments (lowercase)
_BOT_FRAGMENTS = (
    'bot', 'crawl', 'spider', 'slurp', 'mediapartners', 'googlebot',
    'bingbot', 'yahoo', 'semrushbot', 'ahrefsbot', 'dotbot', 'petalbot',
    'python-requests', 'go-http-client', 'curl/', 'wget/', 'libwww',
    'java/', 'apache-httpclient', 'okhttp', 'scrapy', 'headlesschrome',
    'phantomjs', 'selenium',
)


def r_bot_ua(ctx: dict) -> Tuple[int, Optional[str]]:
    """UA matches a known bot/headless-browser fragment → +80."""
    ua = (ctx.get('ua') or '').lower()
    if not ua:
        return 80, 'bot_ua:empty'
    for frag in _BOT_FRAGMENTS:
        if frag in ua:
            return 80, f'bot_ua:{frag}'
    return 0, None


def r_no_referrer(ctx: dict) -> Tuple[int, Optional[str]]:
    """No HTTP Referer header → +20 (direct / injected traffic)."""
    if not ctx.get('referrer'):
        return 20, 'no_referrer'
    return 0, None


def r_click_flood(ctx: dict) -> Tuple[int, Optional[str]]:
    """Same IP sent >30 clicks in the last 60 s → +60."""
    count = ctx.get('click_flood_count', 0)
    threshold = ctx.get('click_flood_threshold', 30)
    if count > threshold:
        return 60, f'click_flood:{count}'
    return 0, None


def r_impossible_geo(ctx: dict) -> Tuple[int, Optional[str]]:
    """Visitor country differs from offer's allowed countries → +30."""
    visitor = (ctx.get('country') or '').upper()
    offer_countries = ctx.get('offer_countries') or []
    if visitor and offer_countries and visitor not in offer_countries:
        return 30, f'impossible_geo:{visitor}'
    return 0, None


def r_repeat_click(ctx: dict) -> Tuple[int, Optional[str]]:
    """Same IP already has a click on this offer in the last 24 h → +25."""
    if ctx.get('repeat_click'):
        return 25, 'repeat_click'
    return 0, None


# ── Composition ────────────────────────────────────────────────────────────

CLICK_RULES = [r_bot_ua, r_no_referrer, r_click_flood, r_impossible_geo, r_repeat_click]


def score_click(ctx: dict) -> Tuple[int, list]:
    """Run all click rules, return (total_score, [reason_tags])."""
    total = 0
    reasons = []
    for rule in CLICK_RULES:
        delta, tag = rule(ctx)
        if delta:
            total += delta
            reasons.append(tag)
    return total, reasons
