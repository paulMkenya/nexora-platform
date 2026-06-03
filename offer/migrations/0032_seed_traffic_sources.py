"""Seed the standard affiliate traffic sources into offer.TrafficSource.

Idempotent: matched by name, missing rows created, existing rows (and any
offer M2M links through them) left untouched. Safe to re-run.
"""
from django.db import migrations


def seed_traffic_sources(apps, schema_editor):
    TrafficSource = apps.get_model('offer', 'TrafficSource')
    from offer.reference import STANDARD_TRAFFIC_SOURCES

    for name in STANDARD_TRAFFIC_SOURCES:
        TrafficSource.objects.get_or_create(name=name)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('offer', '0031_seed_categories'),
    ]

    operations = [
        migrations.RunPython(seed_traffic_sources, noop),
    ]
