from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('offer', '0036_category_slug'),
    ]

    operations = [
        migrations.AddField(
            model_name='offer',
            name='daily_cap',
            field=models.PositiveIntegerField(
                default=0,
                help_text='Max payable conversions per day (site time zone). 0 = no cap.'),
        ),
        migrations.AddField(
            model_name='offer',
            name='allowed_asns',
            field=models.CharField(
                blank=True, default='', max_length=255,
                help_text='Carrier allow list as comma-separated ASNs, e.g. "33771" for '
                          'Safaricom. Blank = any network.'),
        ),
    ]
