import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('brands', '0001_initial'),
        ('tracker', '0015_fraud_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='click',
            name='brand',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='clicks',
                to='brands.brand',
            ),
        ),
        migrations.AddField(
            model_name='conversion',
            name='brand',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='conversions',
                to='brands.brand',
            ),
        ),
    ]
