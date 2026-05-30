from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ('offer', '0022_advertiser_user'),
    ]

    operations = [
        migrations.CreateModel(
            name='AdvertiserPostbackKey',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('secret', models.CharField(max_length=64, unique=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('advertiser', models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='postback_key',
                    to='offer.advertiser',
                )),
            ],
        ),
    ]
