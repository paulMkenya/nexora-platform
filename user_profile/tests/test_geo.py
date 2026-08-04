"""Tests for user_profile/geo.py's country choice plumbing.

Both tests here guard the same class of bug: a query that runs too early.
`choices=country_choices` sits on model fields, so Django's system checks
evaluate it during `migrate` — on a database whose tables that command has
not created yet. And CountryListField is declared in form class bodies
(smartlinks.admin.RoutingRuleInlineForm), so anything it evaluates eagerly
runs at import time, before the app registry is ready. Either one raising
makes an empty database unmigratable.
"""
from unittest.mock import patch

import pytest
from countries_plus.models import Country
from django.db import ProgrammingError

from user_profile.geo import CountryListField, country_choices


def _country(iso, name, iso3, numeric):
    return Country.objects.create(iso=iso, name=name, iso3=iso3, iso_numeric=numeric)


@pytest.mark.django_db
class TestCountryChoices:
    def test_returns_countries_sorted_by_name(self):
        _country('US', 'United States', 'USA', 840)
        _country('KE', 'Kenya', 'KEN', 404)
        assert country_choices(include_blank=False) == [
            ('KE', 'Kenya (KE)'), ('US', 'United States (US)')]

    def test_blank_option_is_first_when_requested(self):
        _country('KE', 'Kenya', 'KEN', 404)
        choices = country_choices()
        assert choices[0] == ('', '— Select country —')
        assert choices[1] == ('KE', 'Kenya (KE)')

    def test_empty_table_yields_only_the_blank_option(self):
        assert country_choices() == [('', '— Select country —')]
        assert country_choices(include_blank=False) == []

    def test_missing_table_degrades_instead_of_raising(self):
        """The unmigrated-database case: system checks evaluate the model
        fields' choices during `migrate`, so raising here would mean the
        command that creates the table can't run until the table exists."""
        with patch('user_profile.geo.Country.objects') as mock_objects:
            mock_objects.order_by.side_effect = ProgrammingError(
                'relation "countries_plus_country" does not exist')
            assert country_choices() == [('', '— Select country —')]
            assert country_choices(include_blank=False) == []


@pytest.mark.django_db
class TestCountryListField:
    def test_construction_does_not_query(self):
        """Declared in a form class body, so a query here fires at import."""
        with patch('user_profile.geo.country_choices') as mock_choices:
            CountryListField()
        mock_choices.assert_not_called()

    def test_choices_are_read_per_instance_not_frozen(self):
        field = CountryListField()
        assert list(field.choices) == []
        _country('KE', 'Kenya', 'KEN', 404)
        assert list(CountryListField().choices) == [('KE', 'Kenya (KE)')]

    def test_no_blank_option_on_the_multi_select(self):
        _country('KE', 'Kenya', 'KEN', 404)
        assert ('', '— Select country —') not in list(CountryListField().choices)

    def test_round_trips_the_csv_column_shape(self):
        _country('KE', 'Kenya', 'KEN', 404)
        _country('US', 'United States', 'USA', 840)
        field = CountryListField()
        assert field.clean(['KE', 'US']) == 'KE,US'
        assert field.prepare_value('KE,US') == ['KE', 'US']
        assert field.prepare_value('') == []
