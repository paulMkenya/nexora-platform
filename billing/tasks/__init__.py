"""Import task submodules so Celery autodiscovery registers their tasks.

``autodiscover_tasks()`` imports this package but not its submodules, so the
``@_celery.task`` functions are only registered if imported. The beat-scheduled
``generate_monthly_invoices`` was previously never imported and failed on the
worker with ``KeyError`` when due. See ``offer/tasks/__init__.py`` for the same
pattern.
"""
from . import debit, invoice, topup  # noqa: F401
