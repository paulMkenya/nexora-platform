"""Track B autologin (native SSO) configuration — one flag, defaults in code.

The feature is OFF by default and the default lives here, not in an env file:
an absent environment variable must mean off, never on. `is_enabled()` is the
only thing that reads the flag, so there is exactly one answer to "is this
live?" for the router, the issuer, the middleware and the doc generator.

Built ahead of demand (see docs/adr/0001-native-sso-autologin.md). Nothing
consumes it yet, which is precisely why the flag is not negotiable.
"""
import logging

from django.conf import settings

logger = logging.getLogger(__name__)

# Hard ceiling. A signed bearer link that logs someone straight into an account
# is a credential; a long TTL turns a leaked URL (Referer header, proxy log,
# pasted into a ticket) into a standing key. Configuration cannot exceed this.
TTL_CEILING_SECONDS = 600

DEFAULT_TTL_SECONDS = 120
DEFAULT_CLOCK_SKEW_TOLERANCE_SECONDS = 5
DEFAULT_ISSUE_RATE_PER_HOUR = 30
DEFAULT_REDEEM_RATE_PER_HOUR = 60

SIGNING_SALT = 'sso.autologin.v1'


class AutologinDisabled(RuntimeError):
    """Raised by any mint/redeem path while the feature is off."""


def is_enabled():
    return bool(getattr(settings, 'SSO_AUTOLOGIN_ENABLED', False))


def ttl_seconds():
    """Configured TTL, clamped to the ceiling. Clamping rather than raising is
    deliberate: a misconfigured-too-long TTL should degrade to the safe bound,
    not take the feature down in a way someone might 'fix' by disabling the
    guard."""
    raw = int(getattr(settings, 'SSO_TOKEN_TTL_SECONDS', DEFAULT_TTL_SECONDS))
    if raw > TTL_CEILING_SECONDS:
        logger.warning(
            'SSO_TOKEN_TTL_SECONDS=%s exceeds the %ss ceiling; clamping.',
            raw, TTL_CEILING_SECONDS,
        )
        return TTL_CEILING_SECONDS
    return max(1, raw)


def clock_skew_tolerance_seconds():
    return int(getattr(
        settings, 'SSO_CLOCK_SKEW_TOLERANCE_SECONDS', DEFAULT_CLOCK_SKEW_TOLERANCE_SECONDS))


def issue_rate_per_hour():
    return int(getattr(settings, 'SSO_ISSUE_RATE_PER_HOUR', DEFAULT_ISSUE_RATE_PER_HOUR))


def redeem_rate_per_hour():
    return int(getattr(settings, 'SSO_REDEEM_RATE_PER_HOUR', DEFAULT_REDEEM_RATE_PER_HOUR))
