import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('brands', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='APIKey',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ('client_id', models.UUIDField(default=None, editable=False, unique=True)),
                ('secret', models.CharField(db_index=True, editable=False, max_length=64, unique=True)),
                ('name', models.CharField(max_length=64)),
                ('is_active', models.BooleanField(default=True)),
                ('requests_per_hour', models.IntegerField(default=1000)),
                ('last_used_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('user', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='api_keys',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={'ordering': ('-created_at',)},
        ),
        migrations.CreateModel(
            name='WebhookEndpoint',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ('url', models.URLField(max_length=500)),
                ('secret', models.CharField(max_length=64)),
                ('events', models.JSONField(default=list)),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('brand', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='webhook_endpoints',
                    to='brands.brand',
                )),
            ],
            options={'ordering': ('-created_at',)},
        ),
        migrations.CreateModel(
            name='WebhookDelivery',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ('event', models.CharField(max_length=64)),
                ('payload', models.JSONField()),
                ('status', models.CharField(
                    choices=[('pending', 'Pending'), ('delivered', 'Delivered'), ('failed', 'Failed')],
                    default='pending',
                    max_length=16,
                )),
                ('attempts', models.IntegerField(default=0)),
                ('next_retry_at', models.DateTimeField(blank=True, null=True)),
                ('last_error', models.TextField(blank=True, default='')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('delivered_at', models.DateTimeField(blank=True, null=True)),
                ('endpoint', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='deliveries',
                    to='public_api.webhookendpoint',
                )),
            ],
            options={'ordering': ('-created_at',)},
        ),
    ]
