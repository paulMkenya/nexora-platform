"""Standardize stored country values to ISO-3166-1 alpha-2 codes.

The ``country`` columns on user_profile.Profile and offer.Advertiser were just
added (blank by default), so in practice there is nothing to convert. This
migration is the safety net required by the spec: should any free-text country
value exist (e.g. a full country name), it is mapped to its alpha-2 code via
countries_plus. Values already equal to a valid alpha-2 code are left as-is.
Unmatched values are cleared to blank and logged — data is never silently lost.
"""
import logging

from django.db import migrations

logger = logging.getLogger(__name__)


def _build_lookup(Country):
    by_code = set()
    by_name = {}
    by_iso3 = {}
    for c in Country.objects.all():
        by_code.add(c.iso.upper())
        by_name[c.name.strip().lower()] = c.iso
        if c.iso3:
            by_iso3[c.iso3.upper()] = c.iso
    return by_code, by_name, by_iso3


def _standardize_model(model, by_code, by_name, by_iso3, label):
    for obj in model.objects.exclude(country='').exclude(country__isnull=True):
        raw = (obj.country or '').strip()
        if not raw:
            continue
        upper = raw.upper()
        if upper in by_code:  # already a valid alpha-2 code
            if obj.country != upper:
                obj.country = upper
                obj.save(update_fields=['country'])
            continue
        mapped = by_name.get(raw.lower()) or by_iso3.get(upper)
        if mapped:
            obj.country = mapped
            obj.save(update_fields=['country'])
            logger.info('country backfill: %s #%s "%s" -> %s', label, obj.pk, raw, mapped)
        else:
            logger.warning(
                'country backfill: %s #%s unmatched value "%s" -> cleared', label, obj.pk, raw
            )
            obj.country = ''
            obj.save(update_fields=['country'])


def standardize(apps, schema_editor):
    Country = apps.get_model('countries_plus', 'Country')
    Profile = apps.get_model('user_profile', 'Profile')
    Advertiser = apps.get_model('offer', 'Advertiser')

    by_code, by_name, by_iso3 = _build_lookup(Country)
    _standardize_model(Profile, by_code, by_name, by_iso3, 'Profile')
    _standardize_model(Advertiser, by_code, by_name, by_iso3, 'Advertiser')


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('offer', '0028_seed_currencies'),
        ('user_profile', '0007_profile_country'),
        ('countries_plus', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(standardize, noop),
    ]
