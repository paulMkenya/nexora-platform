"""Every Celery task this codebase defines must be reachable by the WORKER.

WHY THIS EXISTS. `autodiscover_tasks()` imports `<app>.tasks` and nothing more.
An app whose tasks live in a `tasks/` PACKAGE with an empty `__init__.py`
(billing, payouts, smartlinks, postback, tracker) therefore gets none of its
tasks registered, and neither does a task defined outside the tasks path at all
(leadgen/postback_delivery.py). Several registered anyway — but only by
accident, when some unrelated import chain at startup happened to pull the
module in.

The failure is silent in the worst way. `.delay()` on the SENDING side succeeds:
it just publishes a name to Redis. The worker then answers "Received
unregistered task of type ...", discards the message, and carries on. No retry,
no dead-letter, no alert, and a PostbackDelivery row left at attempts=0
forever, looking merely slow.

That is how affiliate postbacks, monthly invoice generation, payout-request
generation and the smart-link cache refresh were all dead in production while
every dashboard showed green.

THE CHECK IS DELIBERATELY STATIC — it reads files and never imports a task
module. The first version of this file imported each module and then asserted
it was in `_celery.tasks`, which passed against the KNOWN-BROKEN tree: the
import itself is what registers the task, so the assertion could never fail.
Reachability is a property of what the worker imports at startup, so it has to
be answered without importing anything.
"""
import re
from pathlib import Path

import pytest
from django.apps import apps

from project._celery import _celery

BASE_DIR = Path(__file__).resolve().parent.parent.parent

# The decorator forms actually used in this codebase.
_TASK_DECORATOR = re.compile(r'^\s*@(?:_celery|app|shared)[\w.]*\.task\b|^\s*@shared_task\b', re.M)

# `from .cache_offers import cache_offers` in a tasks/__init__.py. Leading \s*
# means a commented-out line (tracker/tasks/__init__.py has four) correctly does
# NOT count as reachable — because it isn't.
_REEXPORT = re.compile(r'^\s*from\s+\.(\w+)\s+import\b', re.M)

_SKIP_DIRS = {'.git', '.claude', 'node_modules', 'staticfiles', 'venv', '.venv'}


def _modules_defining_tasks():
    """Every non-test module in the repo containing a task decorator."""
    found = set()
    for path in BASE_DIR.rglob('*.py'):
        parts = set(path.relative_to(BASE_DIR).parts)
        if parts & _SKIP_DIRS or 'tests' in parts or path.name.startswith('test_'):
            continue
        try:
            source = path.read_text(encoding='utf-8')
        except (OSError, UnicodeDecodeError):
            continue
        if _TASK_DECORATOR.search(source):
            found.add('.'.join(path.relative_to(BASE_DIR).with_suffix('').parts))
    return found


def _reachable_modules():
    """What the worker imports at startup, derived WITHOUT importing anything:
    `<app>.tasks` for every installed app, any submodule that app's
    tasks/__init__.py re-exports, and everything in conf.imports."""
    reachable = set(_celery.conf.imports or ())
    for app_config in apps.get_app_configs():
        app = app_config.name
        app_dir = BASE_DIR / Path(*app.split('.'))
        if (app_dir / 'tasks.py').exists():
            reachable.add(f'{app}.tasks')
        pkg_init = app_dir / 'tasks' / '__init__.py'
        if pkg_init.exists():
            reachable.add(f'{app}.tasks')
            for match in _REEXPORT.finditer(pkg_init.read_text(encoding='utf-8')):
                reachable.add(f'{app}.tasks.{match.group(1)}')
    return reachable


def test_every_task_module_is_reachable_by_the_worker():
    """The core guarantee. A module defining a task must be one the worker
    actually imports — not one that merely happens to get imported when some
    view elsewhere pulls it in."""
    unreachable = sorted(_modules_defining_tasks() - _reachable_modules())
    assert not unreachable, (
        'These modules define Celery tasks the worker never imports, so every message '
        'sent to them is discarded unregistered. Add each to _celery.conf.imports in '
        f'project/_celery.py: {unreachable}')


def test_every_beat_scheduled_task_is_reachable():
    """A scheduled task that isn't registered fires on every tick, gets
    discarded, and logs where nobody reads. smartlinks.tasks.cache
    .cache_smart_links did exactly that every 60 seconds."""
    reachable = _reachable_modules()
    missing = sorted(
        task for task in (cfg['task'] for cfg in (_celery.conf.beat_schedule or {}).values())
        # 'a.b.c.func' -> module 'a.b.c'
        if task.rsplit('.', 1)[0] not in reachable
    )
    assert not missing, f'beat_schedule references tasks the worker cannot run: {missing}'


def test_configured_imports_all_resolve():
    """A stale entry in conf.imports crashes the worker on startup. Loud, but
    only once it reaches production — catch it here. This one DOES import, on
    purpose: resolving is the whole assertion."""
    import importlib
    for dotted in _celery.conf.imports or ():
        importlib.import_module(dotted)


@pytest.mark.parametrize('module', [
    'leadgen.postback_delivery',
    'payouts.tasks.generate',
    'billing.tasks.invoice',
    'smartlinks.tasks.cache',
])
def test_the_four_that_were_silently_dead(module):
    """Named individually so a regression says WHICH capability broke rather
    than just 'a task is missing'. Each was unregistered in production:
    affiliate postbacks never delivered, invoices never generated, payout
    requests never created, smart-link cache never refreshed."""
    assert module in _reachable_modules()
