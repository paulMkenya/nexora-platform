"""Shared helpers for country selection and display.

The single source of country data is the ``countries_plus`` app (252 countries
already loaded). We standardise on the ISO-3166-1 alpha-2 ``iso`` code as the
stored value everywhere.
"""
from django import forms

from countries_plus.models import Country


def country_choices(include_blank=True):
    """Return [(iso, 'Name (ISO)'), ...] sorted alphabetically by name.

    Sourced exclusively from ``countries_plus``. Safe to call when the table is
    empty (returns just the blank option).
    """
    choices = [
        (c.iso, f'{c.name} ({c.iso})')
        for c in Country.objects.order_by('name').only('iso', 'name')
    ]
    if include_blank:
        return [('', '— Select country —')] + choices
    return choices


def iso_to_flag(code):
    """Convert an ISO-3166-1 alpha-2 code to its flag emoji (regional indicators).

    Returns '' for empty/invalid input.
    """
    if not code or len(code) != 2 or not code.isalpha():
        return ''
    code = code.upper()
    return ''.join(chr(0x1F1E6 + ord(ch) - ord('A')) for ch in code)


def country_name(code):
    """Look up the display name for an alpha-2 code, falling back to the code."""
    if not code:
        return ''
    c = Country.objects.filter(iso=code.upper()).only('name').first()
    return c.name if c else code


def country_display(code):
    """Return 'flag Name' for display, or '' when no code is stored."""
    if not code:
        return ''
    flag = iso_to_flag(code)
    name = country_name(code)
    return f'{flag} {name}'.strip()


class CountryListField(forms.MultipleChoiceField):
    """A multi-select country field for a CharField column that stores its
    value as a comma-separated ISO-alpha-2 string (e.g.
    smartlinks.RoutingRule.countries — "US,GB") rather than a real M2M
    relation. Renders a <select multiple> sourced from country_choices();
    converts to/from the CSV string on the ModelForm's behalf so the field
    can be dropped straight onto a CharField with no other model changes."""

    def __init__(self, *, required=False, **kwargs):
        kwargs.setdefault('choices', country_choices(include_blank=False))
        kwargs.setdefault('widget', forms.SelectMultiple(attrs={'size': 8}))
        super().__init__(required=required, **kwargs)

    def prepare_value(self, value):
        if isinstance(value, str):
            value = [v for v in value.split(',') if v]
        return super().prepare_value(value)

    def clean(self, value):
        codes = super().clean(value)
        return ','.join(codes)
