import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('brands', '0001_initial'),
        ('user_profile', '0004_profile_role'),
    ]

    operations = [
        migrations.AddField(
            model_name='profile',
            name='brand',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='users',
                to='brands.brand',
            ),
        ),
    ]
