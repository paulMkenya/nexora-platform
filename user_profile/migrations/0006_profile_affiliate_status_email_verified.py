from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('user_profile', '0005_profile_brand'),
    ]

    operations = [
        migrations.AddField(
            model_name='profile',
            name='affiliate_status',
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
            model_name='profile',
            name='email_verified',
            field=models.BooleanField(default=False),
        ),
    ]
