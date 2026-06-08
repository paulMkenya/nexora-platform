"""NOWPayments provider package.

The home for the NOWPayments integration, structured so the distinct API surfaces
can live side by side without a rewrite:

  * ``base.py``     — shared transport: base-URL resolution + mainnet guard, JWT
                      auth with in-memory caching and a single 401-refresh-retry,
                      the ``_request`` helper, and ``NowPaymentsError``.
  * ``payouts.py``  — ``NowPaymentsPayoutClient`` (Mass Payouts API).
  * ``ipn.py``      — IPN signature verification (HMAC-SHA512, fail-closed).
  * ``payments.py`` — FUTURE (separate deposits track): a payments/deposits client
                      reusing ``base.py``. Intentionally not created yet.

PR #11 wired ``NowPaymentsPayoutClient`` beneath the withdrawal control layer (see
``payouts.providers.dispatch._dispatch_crypto``) and added the IPN webhook, and
DELETED the legacy provider that used to live at ``payouts/crypto/nowpayments.py``.
The client stays INERT until both gates (``CRYPTO_DISPATCH_ENABLED`` +
``NOWPAYMENTS_ALLOW_MAINNET``) are deliberately set live.
"""
from .base import NowPaymentsError
from .payouts import NowPaymentsPayoutClient

__all__ = ['NowPaymentsError', 'NowPaymentsPayoutClient']
