"""NOWPayments provider package (sandbox-guarded).

This is the new home for the NOWPayments integration, structured so the three
distinct API surfaces can live side by side without a rewrite:

  * ``base.py``     — shared transport: base-URL resolution + mainnet guard, JWT
                      auth with in-memory caching and a single 401-refresh-retry,
                      the ``_request`` helper, and ``NowPaymentsError``.
  * ``payouts.py``  — THIS PR: ``NowPaymentsPayoutClient`` (Mass Payouts API).
  * ``payments.py`` — FUTURE (separate deposits track): a payments/deposits client
                      reusing ``base.py``. Intentionally not created in this PR.

Nothing here is wired into the dispatch path yet (see PR #11). The legacy provider
at ``payouts/crypto/nowpayments.py`` is deliberately left untouched and frozen.
"""
from .base import NowPaymentsError
from .payouts import NowPaymentsPayoutClient

__all__ = ['NowPaymentsError', 'NowPaymentsPayoutClient']
