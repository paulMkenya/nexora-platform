from django.db import migrations, models


def grandfather_existing_advertisers(apps, schema_editor):
    """Existing advertisers predate self-registration / approval gating.

    They were created by staff via the Django admin or the API, so they are
    trusted: grandfather every existing row to APPROVED + email_verified. This
    keeps their live offers visible to affiliates and their self-service offer
    flow working — the new PENDING default only applies to advertisers who
    self-register from here on.
    """
    Advertiser = apps.get_model('offer', 'Advertiser')
    Advertiser.objects.update(advertiser_status='APPROVED', email_verified=True)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('offer', '0032_seed_traffic_sources'),
    ]

    operations = [
        migrations.AddField(
            model_name='advertiser',
            name='advertiser_status',
            field=models.CharField(
                choices=[
                    ('PENDING', 'Pending'),
                    ('APPROVED', 'Approved'),
                    ('REJECTED', 'Rejected'),
                    ('SUSPENDED', 'Suspended'),
                ],
                default='PENDING',
                max_length=10,
            ),
        ),
        migrations.AddField(
            model_name='advertiser',
            name='email_verified',
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(grandfather_existing_advertisers, noop_reverse),
    ]
