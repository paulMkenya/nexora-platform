"""Seed the offer.Currency table with all ISO-4217 world currencies.

Idempotent: existing rows are updated in place (matched by code) so stored
currency values stay valid and re-running is safe.
"""
from django.db import migrations


def seed_currencies(apps, schema_editor):
    Currency = apps.get_model('offer', 'Currency')
    from offer.currencies import ISO_4217_CURRENCIES

    for code, name, symbol in ISO_4217_CURRENCIES:
        obj = Currency.objects.filter(code=code).first()
        if obj is None:
            Currency.objects.create(code=code, name=name, symbol=symbol)
        else:
            # Keep the existing row (preserves FKs from offer.Payout); refresh
            # name/symbol to the canonical values.
            obj.name = name
            obj.symbol = symbol
            obj.save(update_fields=['name', 'symbol'])


def noop(apps, schema_editor):
    # Non-destructive reverse: leave seeded currencies in place.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('offer', '0027_alter_currency_options_advertiser_country_and_more'),
    ]

    operations = [
        migrations.RunPython(seed_currencies, noop),
    ]
