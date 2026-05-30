"""
Conversion-level fraud rules — pure functions.

Context keys:
  click_to_conversion_seconds, payout, avg_payout, conversion_velocity,
  conversion_velocity_threshold
"""
from typing import Optional, Tuple

# Minimum seconds between click and conversion to be plausible
MIN_CLICK_TO_CONVERSION = 5

CONVERSION_RULES_CONFIG = {
    'velocity_threshold': 10,       # conversions per hour from same affiliate+offer
    'min_click_seconds': MIN_CLICK_TO_CONVERSION,
    'payout_anomaly_multiplier': 3,  # flag if payout > N× average
}


def r_short_click_to_conversion(ctx: dict) -> Tuple[int, Optional[str]]:
    """Conversion arrived < 5 s after the click → +50 (bot automation)."""
    secs = ctx.get('click_to_conversion_seconds')
    min_secs = ctx.get('min_click_seconds', MIN_CLICK_TO_CONVERSION)
    if secs is not None and secs < min_secs:
        return 50, f'short_c2c:{secs}s'
    return 0, None


def r_conversion_velocity(ctx: dict) -> Tuple[int, Optional[str]]:
    """Too many conversions per hour from same affiliate+offer → +40."""
    velocity = ctx.get('conversion_velocity', 0)
    threshold = ctx.get('conversion_velocity_threshold', CONVERSION_RULES_CONFIG['velocity_threshold'])
    if velocity > threshold:
        return 40, f'conv_velocity:{velocity}'
    return 0, None


def r_payout_anomaly(ctx: dict) -> Tuple[int, Optional[str]]:
    """Payout is much higher than the average for this offer → +35."""
    payout = ctx.get('payout', 0)
    avg = ctx.get('avg_payout', 0)
    multiplier = ctx.get('payout_anomaly_multiplier', CONVERSION_RULES_CONFIG['payout_anomaly_multiplier'])
    if avg and payout > avg * multiplier:
        return 35, f'payout_anomaly:{payout:.2f}x{avg:.2f}'
    return 0, None


CONVERSION_RULES = [r_short_click_to_conversion, r_conversion_velocity, r_payout_anomaly]


def score_conversion(ctx: dict) -> Tuple[int, list]:
    """Run all conversion rules, return (total_score, [reason_tags])."""
    total = 0
    reasons = []
    for rule in CONVERSION_RULES:
        delta, tag = rule(ctx)
        if delta:
            total += delta
            reasons.append(tag)
    return total, reasons
