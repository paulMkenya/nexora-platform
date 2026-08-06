"""Keep autologin tokens out of logs, error trackers and APM traces.

A token IS a login. If one reaches a log line, an exception payload or a
Sentry/Datadog breadcrumb, then anyone with log access has the account for as
long as the token lives — and log retention outlives a 120-second TTL by years.

Attached as a filter so it applies wherever it is wired, including handlers we
do not own. It rewrites both the format string and the interpolation args,
because `logger.info('...%s', url)` keeps the URL in `record.args` where a
naive message-only filter would miss it.
"""
import re

# token=<value> in a query string, and the bare signed-token shape
# (base64ish ":" base64ish ":" base64ish) that django.core.signing produces.
_PATTERNS = [
    re.compile(r'(?i)(token=)[A-Za-z0-9_\-:.]+'),
    re.compile(r'\b[A-Za-z0-9_\-]{8,}:[A-Za-z0-9_\-]{6,}:[A-Za-z0-9_\-]{20,}\b'),
]

MASK = '[REDACTED-AUTOLOGIN]'


def _scrub(value):
    if not isinstance(value, str):
        return value
    out = _PATTERNS[0].sub(rf'\1{MASK}', value)
    out = _PATTERNS[1].sub(MASK, out)
    return out


class RedactAutologinTokens:
    """logging.Filter — never drops a record, only masks it."""

    def filter(self, record):
        try:
            if isinstance(record.msg, str):
                record.msg = _scrub(record.msg)
            if record.args:
                if isinstance(record.args, dict):
                    record.args = {k: _scrub(v) for k, v in record.args.items()}
                else:
                    record.args = tuple(_scrub(a) for a in record.args)
        except Exception:
            # A logging filter must never break the thing it is logging.
            pass
        return True
