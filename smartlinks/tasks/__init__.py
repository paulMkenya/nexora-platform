"""Import task submodules so Celery autodiscovery registers their tasks.

``autodiscover_tasks()`` imports this package but does not recurse into
submodules, so the ``@_celery.task`` functions in ``cache`` / ``click`` are only
registered if something imports them. ``cache_smart_links`` is beat-scheduled
(see ``project/_celery.py``) and was previously never imported, so the worker
rejected it every cycle with ``KeyError``. Same pattern as
``offer/tasks/__init__.py``.
"""
from . import cache, click  # noqa: F401
