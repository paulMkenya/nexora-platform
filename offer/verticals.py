"""The single source of vertical choices for dropdowns.

offer.Category IS the vertical taxonomy — its own field help calls the rows
verticals — so this module deliberately adds no second model. It mirrors
offer.currencies.currency_choices and user_profile.geo.country_choices: one
helper every dropdown calls, so a vertical added in one place appears
everywhere.

WHY THE INBOUND API IS NOT CONSTRAINED TO THIS LIST. Affiliates already submit
free-text verticals through /api/leads/submit, and several live integrations
send values of their own. Turning the field into a closed vocabulary would
reject that traffic outright. The split matches the one this app already draws
between canonical_status (a fixed vocabulary we guarantee) and buyer_status
(whatever the counterparty says): operator-facing dropdowns use the taxonomy,
the wire stays tolerant.
"""


def vertical_choices(include_blank=False):
    """[(slug, name), ...] for dropdowns, sourced from the seeded
    offer.Category table so a vertical an operator adds shows up everywhere.

    Falls back to the static reference list when the table cannot answer —
    same shape as offer.currencies.currency_choices, and load-bearing for one
    more reason than an empty test database: this callable is attached to a
    MODEL FIELD, so Django evaluates it during makemigrations and system checks.
    Those run against a database whose Category.slug column may not exist yet
    (it is added by offer/0036), and an unguarded query there fails the whole
    command with a ProgrammingError. The fallback keeps the field usable before
    its own migration has been applied.

    A plain function reference — pass it, never call it, when handing it to a
    model or form field, so Django re-evaluates it per render instead of baking
    today's list into migration state. Same reasoning as country_choices.
    """
    from .reference import CATEGORY_SLUGS

    try:
        from .models import Category
        rows = list(
            Category.objects.exclude(slug='')
            .order_by('name')
            .values_list('slug', 'name')
        )
    except Exception:
        # Deliberately broad. The failures here are all environmental rather
        # than logical — a missing column before 0036 applies, no database
        # during a system check, the app registry not ready — and every one of
        # them should degrade to the static list rather than take down the
        # command that touched the field. Narrowing this to DatabaseError has
        # already proved insufficient once: makemigrations raised
        # ProgrammingError for the not-yet-added column.
        rows = []
    if not rows:
        rows = sorted(
            ((slug, name) for name, slug in CATEGORY_SLUGS.items()),
            key=lambda pair: pair[1],
        )
    if include_blank:
        return [('', '— Any vertical —')] + list(rows)
    return list(rows)


def vertical_slugs():
    return [slug for slug, _ in vertical_choices()]
