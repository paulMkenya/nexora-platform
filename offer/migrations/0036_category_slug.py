"""Give offer.Category a machine-readable slug, and seed the widened vertical list.

Two operations that belong together: the slug is what makes a Category usable as
a vertical on the wire, and the widened STANDARD_CATEGORIES list is only useful
once its rows carry one.

⚠️ THE DB-LEVEL DEFAULT IS LOAD-BEARING — do not drop it as redundant. Django
manages defaults in Python: AddField backfills existing rows then DROPS the
database-level default, leaving a NOT NULL column with none. Between `migrate`
and the new image serving traffic, the RUNNING release's model does not know the
column exists, so its INSERTs omit it and every write to offer_category fails.
That is how leadgen/0016 broke all lead capture on 2026-08-17; 0017, 0018 and
leadgen/0019 apply the same remedy.

Idempotent, and non-destructive by design: rows are matched by name, a missing
slug is filled, and an operator-created category the reference list has never
heard of is left completely alone rather than being guessed at.
"""
from django.db import migrations, models


def seed_slugs_and_categories(apps, schema_editor):
    Category = apps.get_model('offer', 'Category')
    from offer.reference import CATEGORY_SLUGS, STANDARD_CATEGORIES

    for name, is_adult in STANDARD_CATEGORIES:
        slug = CATEGORY_SLUGS.get(name, '')
        obj = Category.objects.filter(name=name).first()
        if obj is None:
            Category.objects.create(name=name, is_adult=is_adult, slug=slug)
            continue
        # Only ever FILL a blank slug. Overwriting one would re-label a buyer's
        # reporting mid-campaign, and an operator who set it by hand knows
        # something this file does not.
        if not obj.slug and slug:
            obj.slug = slug
            obj.save(update_fields=['slug'])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('offer', '0035_alter_advertiser_country'),
    ]

    operations = [
        migrations.AddField(
            model_name='category',
            name='slug',
            field=models.SlugField(
                blank=True, default='', max_length=60,
                help_text='Machine value sent to buyers, e.g. "crypto". Leave blank to keep this '
                          'category out of the vertical dropdowns.',
            ),
        ),
        migrations.RunSQL(
            sql="ALTER TABLE offer_category ALTER COLUMN slug SET DEFAULT '';",
            reverse_sql="ALTER TABLE offer_category ALTER COLUMN slug DROP DEFAULT;",
        ),
        migrations.RunPython(seed_slugs_and_categories, noop),
    ]
