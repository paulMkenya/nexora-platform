"""Give Lead.attribution / Lead.language DATABASE-level defaults.

WHY, and why this is not redundant with the field defaults in 0016: Django
manages defaults in Python. ``AddField(default=...)`` uses the default to
backfill existing rows and then DROPS it at the database level, leaving two
``NOT NULL`` columns with no DB default. Any INSERT that does not name them
therefore fails.

That is exactly what a rolling deploy produces. Applying 0016 while the
previous release is still serving means the running code's model has no
``attribution``/``language``, so its INSERTs omit both columns and every lead
capture dies with:

    IntegrityError: null value in column "attribution" of relation
    "leadgen_lead" violates not-null constraint

Observed in production on 2026-08-17: 0016 was applied ahead of the code that
uses it, and lead capture broke instantly. It went unnoticed only because no
lead happened to arrive in the ~40 seconds before the defaults below were added
by hand. This migration is that hand-fix made reproducible, so a fresh database
and production agree and the next environment does not rediscover it.

Once the attribution code IS deployed the ORM always supplies both values and
these defaults are never consulted — they cost nothing and remain the safety
net for the next time a schema change lands ahead of its code.

Idempotent: ``SET DEFAULT`` to the same value is a no-op, so this applies
cleanly to production (where the defaults already exist) and to a fresh
database alike.
"""
from django.db import migrations

SET_DEFAULTS = """
    ALTER TABLE leadgen_lead ALTER COLUMN attribution SET DEFAULT '{}'::jsonb;
    ALTER TABLE leadgen_lead ALTER COLUMN language SET DEFAULT '';
"""

DROP_DEFAULTS = """
    ALTER TABLE leadgen_lead ALTER COLUMN attribution DROP DEFAULT;
    ALTER TABLE leadgen_lead ALTER COLUMN language DROP DEFAULT;
"""


class Migration(migrations.Migration):

    dependencies = [
        ('leadgen', '0016_lead_attribution_lead_language'),
    ]

    operations = [
        # No state_operations: this changes only how the database fills a
        # column nobody named, not the Django model, so makemigrations must
        # not see a difference here and try to "correct" it.
        migrations.RunSQL(sql=SET_DEFAULTS, reverse_sql=DROP_DEFAULTS),
    ]
