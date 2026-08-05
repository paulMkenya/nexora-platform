"""LeadBuyer.brand becomes required — Paul's ruling of 2026-08-05.

A LeadBuyer belongs to exactly one Brand: each brand routes only to its own
buyers, authors its own routing rules, and owns the payout relationship.
There are no shared/platform buyers, so the nullable brand FK (and the
`brand=None` fallback that read it as "available to every brand") is gone.

Two steps, in order, because the second cannot run while any NULL remains:

1. A defensive backfill. Production was already backfilled by hand before
   this migration was written — buyer `op-brandy` -> Nexora, approved by
   Paul, evidenced by all three of its injections being Nexora leads — so
   this is a no-op there. It exists for every OTHER environment (a fresh
   clone, a restored dump, a second install) where a brandless buyer could
   still exist and would otherwise make the AlterField fail with an opaque
   IntegrityError.

   Where a default brand exists, brandless buyers are assigned to it. Where
   one does not, the migration RAISES rather than guessing: which brand owns
   a buyer is a commercial fact about who holds the payout relationship, and
   silently attaching it to an arbitrary brand could route real leads — and
   real money — to the wrong counterparty. Better to stop and make a human
   decide.

2. The schema change itself: null=False, plus on_delete PROTECT instead of
   CASCADE. CASCADE would have let deleting a brand silently destroy its
   buyers and their injection history; brands/lifecycle.py deliberately
   orphans rather than destroys ("SET_NULLs ... orphaning, never destroying
   them"), and PROTECT is the null=False-compatible way to keep that promise.
"""
from django.db import migrations, models
import django.db.models.deletion


def backfill_buyer_brand(apps, schema_editor):
    LeadBuyer = apps.get_model('leadgen', 'LeadBuyer')
    Brand = apps.get_model('brands', 'Brand')

    brandless = LeadBuyer.objects.filter(brand__isnull=True)
    if not brandless.exists():
        return

    default_brand = Brand.objects.filter(is_default=True, is_archived=False).first()
    if default_brand is None:
        names = ', '.join(brandless.values_list('name', flat=True)[:10])
        raise RuntimeError(
            'Cannot make LeadBuyer.brand required: these buyers have no brand and '
            f'there is no default brand to fall back to: {names}. Assign each buyer '
            'to the brand that owns its payout relationship, then re-run migrate. '
            'Refusing to guess — a wrong assignment routes real leads to the wrong '
            'counterparty.'
        )
    brandless.update(brand=default_brand)


def noop_reverse(apps, schema_editor):
    """Reversing only widens the constraint; the assignments stay, which is
    correct — they are real commercial facts, not migration scaffolding."""


class Migration(migrations.Migration):

    # REQUIRED, not decorative: the backfill below and the SET NOT NULL that
    # follows it must share one transaction. A buyer created between the two
    # would make the ALTER fail — atomicity is what turns that into a clean
    # full rollback (re-runnable, no half-applied state) instead of a migration
    # that backfilled and then died. Setting this False reopens that as data
    # corruption. It is Django's default; it is written out because the
    # migration's correctness depends on it.
    atomic = True

    dependencies = [
        ('brands', '0001_initial'),
        ('leadgen', '0010_leadstatusevent_lead_seq_affiliatepostbackconfig_and_more'),
    ]

    operations = [
        migrations.RunPython(backfill_buyer_brand, noop_reverse),
        migrations.AlterField(
            model_name='leadbuyer',
            name='brand',
            field=models.ForeignKey(
                help_text='Every buyer belongs to exactly one brand — there are no '
                          'platform-wide buyers. A brand routes only to its own buyers '
                          'and owns the payout relationship with them.',
                on_delete=django.db.models.deletion.PROTECT,
                related_name='lead_buyers',
                to='brands.brand',
            ),
        ),
    ]
