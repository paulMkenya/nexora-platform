"""What a lead must carry for its DESTINATION to accept it, checked at intake.

WHY THIS EXISTS. Nexora's inbound contract and a buyer box's contract are two
different lists, and the second one is invisible to the affiliate. Hypernet
marks `geo` REQUIRED; our own `country` is optional. So a lead submitted
without `country` was accepted `201`, injected, and rejected by the box with
`Validation error. ("geo" is required)` — the affiliate saw a success, kept no
retry, and the lead was simply gone. Probed live 2026-08-20; three of the
fifty-nine affiliate-API leads on record already carry no country.

Nothing backfills it in practice for this channel either: `tasks.geolocate_lead`
is a no-op without `settings.IPSTACK_TOKEN`, which is unset in production.

THE RULE: fail at the boundary the submitter can actually see. A 400 from us
names the field and is retryable by the affiliate; a 400 from the buyer four
seconds later is not visible to them at all.

WHAT IS DELIBERATELY *NOT* HERE: the required set itself. That is declared by
the CONNECTOR (`LeadBuyerConnector.REQUIRED_LEAD_FIELDS`), because it is a
property of that box's API. Onboarding a box with a different required set is
then a connector attribute, not an edit to intake. The base connector declares
nothing, so every buyer that has not been probed keeps today's exact behaviour.
"""

# Lead attribute -> the name the INBOUND API calls it, so an error message
# names the field the affiliate actually sent (or omitted) rather than our
# internal column. A field absent here is reported under its own name.
API_FIELD_NAMES = {
    'country_iso2': 'country',
}


def missing_buyer_requirements(lead):
    """The inbound-API field names `lead` is missing for the buyer it would
    actually be routed to, or [] if there is nothing to complain about.

    Resolves the destination through the ordinary routing chain, so this
    answers "the box this lead is really going to", not "some box in this
    brand". Returns [] — never an error — when the lead routes nowhere: an
    unroutable lead is a routing gap for an operator to fix, and turning it
    into a validation failure for the affiliate would blame the wrong party
    and reject traffic we could still recover with `redrive_leads`.

    `lead` may be UNSAVED. Nothing here touches lead.pk, so intake can build a
    candidate Lead, check it, and only then decide whether to write a row.
    """
    from .connectors import get_connector
    from .routing import resolve_buyer_chain

    chain = resolve_buyer_chain(lead)
    if not chain:
        return []

    required = getattr(get_connector(chain[0]), 'REQUIRED_LEAD_FIELDS', ())
    return [
        API_FIELD_NAMES.get(attr, attr)
        for attr in required
        if not getattr(lead, attr, '')
    ]
