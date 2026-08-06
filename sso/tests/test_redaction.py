"""A token that reaches a log line is a credential sitting in log retention.

Log retention outlives a 120-second TTL by years, and logs are copied to places
the application never sees — error trackers, APM traces, shipped archives. So
the mask has to happen at the logging layer, not by remembering not to log it.
"""
import logging

from sso.logging_filters import MASK, RedactAutologinTokens


def _record(msg, args=None):
    return logging.LogRecord(
        name='test', level=logging.INFO, pathname=__file__, lineno=1,
        msg=msg, args=args, exc_info=None,
    )


class TestRedaction:
    def test_masks_a_token_in_a_query_string(self):
        rec = _record('redirecting to /sso/autologin/?token=abc123:1x9:signedpart')
        RedactAutologinTokens().filter(rec)
        assert 'abc123' not in rec.getMessage()
        assert MASK in rec.getMessage()

    def test_masks_a_bare_signed_token(self):
        token = 'eyJ1IjoxfQ:1uZ8yQ:kQ7m3nP2xR9wL4vB8sT1yU6iO0pA5dF7gH2jK3lM9nQ'
        rec = _record('issued %s for user', (token,))
        RedactAutologinTokens().filter(rec)
        assert token not in rec.getMessage()
        assert MASK in rec.getMessage()

    def test_masks_tokens_hidden_in_args_not_just_the_message(self):
        """logger.info('...%s', url) keeps the URL in record.args, where a
        message-only filter would miss it entirely."""
        rec = _record('callback %s', ('https://x.test/sso/autologin/?token=SECRETVALUE123',))
        RedactAutologinTokens().filter(rec)
        assert 'SECRETVALUE123' not in rec.getMessage()

    def test_never_drops_a_record(self):
        rec = _record('ordinary line')
        assert RedactAutologinTokens().filter(rec) is True
        assert rec.getMessage() == 'ordinary line'

    def test_survives_a_non_string_arg(self):
        """A filter must never break the thing it is logging."""
        rec = _record('count=%d', (42,))
        assert RedactAutologinTokens().filter(rec) is True
        assert rec.getMessage() == 'count=42'
