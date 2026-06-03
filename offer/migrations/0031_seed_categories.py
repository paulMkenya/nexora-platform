"""Seed the standard affiliate verticals into offer.Category.

Idempotent: rows are matched by name; missing ones are created, the adult flag
is refreshed, and operator-created categories are left untouched. Re-running
only fills gaps — nothing is renamed or deleted.
"""
from django.db import migrations


def seed_categories(apps, schema_editor):
    Category = apps.get_model('offer', 'Category')
    from offer.reference import STANDARD_CATEGORIES

    for name, is_adult in STANDARD_CATEGORIES:
        obj = Category.objects.filter(name=name).first()
        if obj is None:
            Category.objects.create(name=name, is_adult=is_adult)
        elif obj.is_adult != is_adult:
            obj.is_adult = is_adult
            obj.save(update_fields=['is_adult'])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('offer', '0030_offer_targeting_revenue_model'),
    ]

    operations = [
        migrations.RunPython(seed_categories, noop),
    ]
