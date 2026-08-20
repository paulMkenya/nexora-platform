"""The allowlist of connector classes a BoxType may name.

WHY THIS EXISTS — READ BEFORE WIDENING IT.

``BoxType.connector_class`` is a dotted Python path that ``get_connector()``
feeds to Django's ``import_string``. That is safe while only the platform owner
can set it. From 2026-08-20 brand admins may create their own templates, and at
that moment a free-text field naming an arbitrary importable path stops being a
configuration value and becomes a choice of *which code runs* inside our worker
— every class already imported in the process is reachable, and importing a
module executes it.

So the field is no longer free text. It is a choice from this registry, and
``BoxType.clean()`` refuses anything absent from it. The registry lives in CODE,
never in the database: a table an operator can write to would defeat the point
entirely.

ADDING A CONNECTOR is therefore a deliberate engineering act — write the class,
prove it against the real box, then register it here with a description an
operator can actually understand. That is not friction for its own sake: a
connector decides how a lead's payload is built and how a buyer's response is
read, so a wrong one silently mis-sends real consumer data.
"""
from django.utils.functional import lazy

# path -> operator-facing description. The description is shown in the template
# form's dropdown, so write it for someone choosing an integration, not for
# someone reading the source.
CONNECTORS = {
    'leadgen.connectors.LeadBuyerConnector': (
        'Generic REST — JSON body, API key, standard success/duplicate/failure '
        'envelope. Start here: most boxes need nothing else.'
    ),
    'leadgen.connectors.HypernetConnector': (
        'Hypernet CRM (HTN-AFF-SDK) — nested profile object, affc/bxc/vtc '
        'constants, status pulled by registration-date window.'
    ),
    'leadgen.connectors.TrackBoxConnector': (
        'TrackBox by Tigloo — three auth headers, and answers HTTP 200 to '
        'failures with the real verdict in the body.'
    ),
}


def connector_choices():
    """Choices for a form/model field. A plain function reference (not the list
    itself) so Django re-evaluates it per render instead of freezing today's
    registry into migration state — the same reason country_choices is passed
    by reference on Lead.country_iso2."""
    return [(path, f'{path.rsplit(".", 1)[-1]} — {desc}') for path, desc in CONNECTORS.items()]


connector_choices_lazy = lazy(connector_choices, list)


def is_registered(path):
    return path in CONNECTORS


def describe(path):
    return CONNECTORS.get(path, '')
