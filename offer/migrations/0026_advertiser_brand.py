import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('brands', '0001_initial'),
        ('offer', '0025_offer_brand'),
    ]

    operations = [
        migrations.AddField(
            model_name='advertiser',
            name='brand',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='advertisers',
                to='brands.brand',
            ),
        ),
    ]
