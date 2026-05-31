from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('offer', '0026_advertiser_brand'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='currency',
            options={'ordering': ('code',), 'verbose_name_plural': 'Currencies'},
        ),
        migrations.AddField(
            model_name='advertiser',
            name='country',
            field=models.CharField(blank=True, default='', max_length=2),
        ),
        migrations.AddField(
            model_name='currency',
            name='symbol',
            field=models.CharField(blank=True, default='', max_length=8),
        ),
    ]
