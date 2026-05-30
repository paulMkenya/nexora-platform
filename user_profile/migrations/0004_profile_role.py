from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('user_profile', '0003_auto_20200617_2157'),
    ]

    operations = [
        migrations.AddField(
            model_name='profile',
            name='role',
            field=models.CharField(
                choices=[
                    ('AFFILIATE', 'Affiliate'),
                    ('ADVERTISER', 'Advertiser'),
                    ('AFFILIATE_MANAGER', 'Affiliate Manager'),
                    ('NETWORK_ADMIN', 'Network Admin'),
                ],
                default='AFFILIATE',
                max_length=20,
            ),
        ),
    ]
