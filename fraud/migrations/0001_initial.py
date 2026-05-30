import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='FraudWhitelist',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('entry_type', models.CharField(choices=[('ip', 'IP Address'), ('pid', 'Affiliate PID')], max_length=3)),
                ('value', models.CharField(max_length=64, unique=True)),
                ('note', models.CharField(blank=True, default='', max_length=255)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('created_by', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={'ordering': ('-created_at',)},
        ),
    ]
