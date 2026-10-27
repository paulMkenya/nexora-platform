from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tracker', '0016_click_conversion_brand'),
    ]

    operations = [
        migrations.AddField(
            model_name='click',
            name='asn',
            field=models.PositiveIntegerField(blank=True, default=None, null=True),
        ),
        migrations.AddField(
            model_name='click',
            name='isp',
            field=models.CharField(blank=True, default='', max_length=128),
        ),
        migrations.AddField(
            model_name='click',
            name='is_mobile',
            field=models.BooleanField(default=None, null=True),
        ),
        migrations.AddField(
            model_name='conversion',
            name='txid',
            field=models.CharField(blank=True, db_index=True, default='', max_length=64),
        ),
    ]
