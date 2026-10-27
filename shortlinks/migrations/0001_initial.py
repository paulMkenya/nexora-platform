import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('offer', '0037_offer_delivery_controls'),
    ]

    operations = [
        migrations.CreateModel(
            name='ShortLink',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('slug', models.CharField(max_length=64, unique=True, validators=[django.core.validators.RegexValidator(
                    '^[a-z0-9](?:[a-z0-9-]{1,62}[a-z0-9])$',
                    'Use 3-64 lowercase letters, numbers and dashes; start and end with a letter or number.')])),
                ('label', models.CharField(blank=True, default='', max_length=128)),
                ('sub1', models.CharField(blank=True, default='', max_length=500)),
                ('sub2', models.CharField(blank=True, default='', max_length=500)),
                ('sub3', models.CharField(blank=True, default='', max_length=500)),
                ('sub4', models.CharField(blank=True, default='', max_length=500)),
                ('sub5', models.CharField(blank=True, default='', max_length=500)),
                ('is_active', models.BooleanField(default=True)),
                ('clicks', models.PositiveIntegerField(default=0)),
                ('last_click_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('affiliate', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='short_links', to=settings.AUTH_USER_MODEL)),
                ('offer', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='short_links', to='offer.offer')),
            ],
            options={'ordering': ('-created_at',)},
        ),
    ]
