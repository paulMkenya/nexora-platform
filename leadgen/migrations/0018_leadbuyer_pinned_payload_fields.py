"""Add LeadBuyer.pinned_payload_fields.

⚠️ THE DB-LEVEL DEFAULT BELOW IS LOAD-BEARING — do not drop it as redundant.

Django manages defaults in Python: AddField(default=list) backfills existing
rows and then DROPS the database-level default, leaving a NOT NULL column with
none. Between `migrate` and the new image serving traffic, the RUNNING release's
model does not know this column exists, so its INSERTs omit it and every write
to leadgen_leadbuyer fails with

    IntegrityError: null value in column "pinned_payload_fields" ... not-null

That is exactly how leadgen/0016 broke all lead capture on 2026-08-17; 0017 is
the same remedy applied after the fact. Doing it in the same migration keeps the
window closed from the start. The RunSQL is idempotent and reversible.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('leadgen', '0017_lead_attribution_language_db_defaults'),
    ]

    operations = [
        migrations.AddField(
            model_name='leadbuyer',
            name='pinned_payload_fields',
            field=models.JSONField(
                blank=True,
                default=list,
                help_text='Keys in extra_payload_fields that a mapped lead value must not override.',
            ),
        ),
        migrations.RunSQL(
            sql="ALTER TABLE leadgen_leadbuyer "
                "ALTER COLUMN pinned_payload_fields SET DEFAULT '[]'::jsonb;",
            reverse_sql="ALTER TABLE leadgen_leadbuyer "
                        "ALTER COLUMN pinned_payload_fields DROP DEFAULT;",
        ),
    ]
