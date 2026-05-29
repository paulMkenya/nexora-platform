from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('offer', '0021_auto_20200903_2149'),
    ]

    operations = [
        migrations.AddField(
            model_name='advertiser',
            name='user',
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='advertiser_profile',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
