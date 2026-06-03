"""Tests for offer reference data (seeds) and country-targeting logic."""
from django.test import TestCase

from countries_plus.models import Country

from offer.models import (
    ALLOW_ALL, ALLOW_LIST, BLOCK_LIST, Category, Offer, TrafficSource,
)
from offer.reference import STANDARD_CATEGORIES, STANDARD_TRAFFIC_SOURCES


class ReferenceSeedTests(TestCase):
    """The data migrations seed the standard verticals and traffic sources."""

    def test_standard_categories_seeded(self):
        names = set(Category.objects.values_list('name', flat=True))
        for name, _ in STANDARD_CATEGORIES:
            self.assertIn(name, names)

    def test_adult_flag_seeded(self):
        adult = Category.objects.get(name='Adult')
        self.assertTrue(adult.is_adult)
        finance = Category.objects.get(name='Finance')
        self.assertFalse(finance.is_adult)

    def test_standard_traffic_sources_seeded(self):
        names = set(TrafficSource.objects.values_list('name', flat=True))
        for name in STANDARD_TRAFFIC_SOURCES:
            self.assertIn(name, names)


class CountryTargetingTests(TestCase):
    def _country(self, iso, name, iso3, num):
        return Country.objects.get_or_create(
            iso=iso,
            defaults={'name': name, 'iso3': iso3, 'iso_numeric': num})[0]

    def setUp(self):
        self.ng = self._country('NG', 'Nigeria', 'NGA', 566)
        self.gh = self._country('GH', 'Ghana', 'GHA', 288)
        self.ke = self._country('KE', 'Kenya', 'KEN', 404)

    def test_allow_all_accepts_everything(self):
        offer = Offer.objects.create(title='Global', country_mode=ALLOW_ALL)
        self.assertTrue(offer.accepts_country('NG'))
        self.assertTrue(offer.accepts_country('ZZ'))
        self.assertEqual(offer.targeting_display(), 'Global')

    def test_allow_list_only_listed(self):
        offer = Offer.objects.create(title='KE only', country_mode=ALLOW_LIST)
        offer.countries.add(self.ke)
        self.assertTrue(offer.accepts_country('ke'))   # case-insensitive
        self.assertFalse(offer.accepts_country('NG'))
        self.assertEqual(offer.targeting_display(), 'KE only')

    def test_block_list_all_except_listed(self):
        offer = Offer.objects.create(title='Block', country_mode=BLOCK_LIST)
        offer.countries.add(self.ng, self.gh)
        self.assertFalse(offer.accepts_country('NG'))
        self.assertTrue(offer.accepts_country('KE'))
        self.assertEqual(offer.targeting_display(), 'Global except GH, NG')

    def test_empty_allow_list_accepts_nobody(self):
        offer = Offer.objects.create(title='Empty allow', country_mode=ALLOW_LIST)
        self.assertFalse(offer.accepts_country('KE'))
        self.assertEqual(offer.targeting_display(), 'No countries')

    def test_empty_block_list_is_global(self):
        offer = Offer.objects.create(title='Empty block', country_mode=BLOCK_LIST)
        self.assertTrue(offer.accepts_country('KE'))
        self.assertEqual(offer.targeting_display(), 'Global')
