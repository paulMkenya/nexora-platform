"""Static guard: no Lead write may bypass LeadQuerySet.touch().

Django applies `auto_now` in Model.save(), not in QuerySet.update(). Every lead
mutation in this app uses update() deliberately, so a path that calls .update()
instead of .touch() leaves updated_at frozen — and a lead whose state changed
without moving updated_at is invisible to `GET /api/leads?updated_since=...`,
the reconcile poll integrators depend on to notice conversions.

This is an AST check, not a grep, and that distinction is the whole point. The
original hand enumeration used a regex shaped like `Lead.objects.filter(...).
update(`, which silently missed

    Lead.objects.filter(pk=...).exclude(...).update(status=...)

in failover.py — a real lead-loss path that shipped as "enumerated, all
covered". A regex has to anticipate the chain shape; walking the call graph
does not.
"""
import ast
import pathlib

import pytest

APP_ROOT = pathlib.Path(__file__).resolve().parent.parent

# LeadQuerySet.touch() is the sanctioned helper and necessarily calls
# self.update() — it is the one place allowed to.
SANCTIONED = {('models.py', 'touch')}


def _python_sources():
    for path in sorted(APP_ROOT.rglob('*.py')):
        rel = path.relative_to(APP_ROOT)
        if rel.parts[0] in ('tests', 'migrations'):
            continue
        yield path


def _chain_root(node):
    """The leftmost Name of an attribute/call chain: for
    `Lead.objects.filter(x).exclude(y).update(z)` this returns 'Lead',
    regardless of how many calls sit in between."""
    while True:
        if isinstance(node, ast.Attribute):
            node = node.value
        elif isinstance(node, ast.Call):
            node = node.func
        elif isinstance(node, ast.Name):
            return node.id
        else:
            return None


def _enclosing_function(tree, target):
    for fn in ast.walk(tree):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for child in ast.walk(fn):
                if child is target:
                    return fn.name
    return None


def _offending_updates(path):
    tree = ast.parse(path.read_text())
    out = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == 'update'):
            continue
        if _chain_root(node.func) != 'Lead':
            continue
        fn = _enclosing_function(tree, node)
        if (path.name, fn) in SANCTIONED:
            continue
        out.append(f'{path.name}:{node.lineno} (in {fn or "module scope"})')
    return out


def test_no_lead_queryset_update_bypasses_touch():
    offenders = []
    for path in _python_sources():
        offenders.extend(_offending_updates(path))

    assert not offenders, (
        'These write to a Lead via QuerySet.update(), which does NOT advance '
        'updated_at and so hides the change from the reconcile poll. Use '
        '.touch() instead:\n  ' + '\n  '.join(offenders))


def test_the_guard_actually_detects_a_bypass():
    """A guard that cannot fail is not a guard. Feed it the exact shape that
    slipped through the original regex and require a hit."""
    source = (
        'from leadgen.models import Lead\n'
        'def sneaky(lead):\n'
        '    Lead.objects.filter(pk=lead.pk).exclude(status__in=("a",)).update(status="x")\n'
    )
    tree = ast.parse(source)
    hits = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        and n.func.attr == 'update' and _chain_root(n.func) == 'Lead'
    ]
    assert len(hits) == 1, 'the guard would not have caught the failover.py bypass'


@pytest.mark.parametrize('name', ['status_sync.py', 'tasks.py', 'failover.py'])
def test_known_mutating_modules_are_scanned(name):
    """Guards rot when the file they watch is renamed out from under them."""
    assert (APP_ROOT / name).exists(), f'{name} moved — update this guard'
