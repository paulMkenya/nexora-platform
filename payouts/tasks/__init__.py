"""Import task submodules so Celery autodiscovery registers their tasks.

``autodiscover_tasks()`` imports this package but not its submodules, so the
``@_celery.task`` functions are only registered if imported. The beat-scheduled
``generate_payout_requests`` was previously never imported and failed on the
worker with ``KeyError`` every run. (``process_nowpayments_ipn`` happened to
register only because the webhook view imports it.) See
``offer/tasks/__init__.py`` for the same pattern.
"""
from . import generate, ipn  # noqa: F401
