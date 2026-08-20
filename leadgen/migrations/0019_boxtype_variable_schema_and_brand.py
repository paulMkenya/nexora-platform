"""BoxType learns to describe itself, and may belong to one brand.

⚠️ THE DB-LEVEL DEFAULTS BELOW ARE LOAD-BEARING — do not drop them as redundant.

Django manages defaults in Python: AddField backfills existing rows and then
DROPS the database-level default, leaving a NOT NULL column with none. Between
`migrate` and the new image serving traffic, the RUNNING release's model does
not know these columns exist, so its INSERTs omit them and every write to
leadgen_boxtype fails. That is exactly how leadgen/0016 broke all lead capture
on 2026-08-17; 0017 and 0018 apply the same remedy. Doing it in the same
migration keeps the window closed from the start.

`brand` is nullable by design, not by convenience: NULL means "platform
template, available to every brand" — see BoxType.brand's docstring for why that
is the correct reading for an outbound integration recipe, and the opposite of
the rule for offers.
"""
import django.db.models.deletion
from django.db import migrations, models

import leadgen.connector_registry


class Migration(migrations.Migration):

    dependencies = [
        ('leadgen', '0018_leadbuyer_pinned_payload_fields'),
        ('brands', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='boxtype',
            name='variable_schema',
            field=models.JSONField(
                blank=True, default=list,
                help_text='The fields an operator fills in when creating a buyer on this template.',
            ),
        ),
        migrations.AddField(
            model_name='boxtype',
            name='brand',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='box_types', to='brands.brand',
                help_text='Leave empty for a platform template available to every brand.',
            ),
        ),
        migrations.AlterField(
            model_name='boxtype',
            name='connector_class',
            # A function REFERENCE, never the evaluated list — same reason
            # Lead.country_iso2 passes country_choices this way. Baking today's
            # registry into migration state would mean a stale dropdown the
            # moment a connector is added, and a pointless migration each time.
            field=models.CharField(
                default='leadgen.connectors.LeadBuyerConnector', max_length=200,
                choices=leadgen.connector_registry.connector_choices,
                help_text='Which integration this template speaks. Chosen from the vetted registry.',
            ),
        ),
        migrations.RunSQL(
            sql="ALTER TABLE leadgen_boxtype "
                "ALTER COLUMN variable_schema SET DEFAULT '[]'::jsonb;",
            reverse_sql="ALTER TABLE leadgen_boxtype "
                        "ALTER COLUMN variable_schema DROP DEFAULT;",
        ),
    ]
