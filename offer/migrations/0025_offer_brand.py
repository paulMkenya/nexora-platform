import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('brands', '0001_initial'),
        ('offer', '0024_offer_mmp_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='offer',
            name='brand',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='offers',
                to='brands.brand',
            ),
        ),
    ]
