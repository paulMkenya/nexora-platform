import uuid
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
            name='SmartLink',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=128)),
                ('alias', models.SlugField(max_length=64, unique=True)),
                ('default_url', models.CharField(max_length=1024)),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'ordering': ('name',),
            },
        ),
        migrations.CreateModel(
            name='RoutingRule',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('priority', models.IntegerField(default=100)),
                ('destination_url', models.CharField(max_length=1024)),
                ('countries', models.CharField(
                    blank=True, default='', max_length=500,
                    help_text='ISO-2 codes, comma-separated, e.g. US,GB. Leave empty to match any country.',
                )),
                ('device_type', models.CharField(
                    choices=[('any', 'Any'), ('mobile', 'Mobile'), ('desktop', 'Desktop'), ('tablet', 'Tablet')],
                    default='any', max_length=10,
                )),
                ('is_active', models.BooleanField(default=True)),
                ('smart_link', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='rules',
                    to='smartlinks.smartlink',
                )),
            ],
            options={
                'ordering': ('priority',),
            },
        ),
        migrations.CreateModel(
            name='SmartLinkClick',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('ip', models.GenericIPAddressField(blank=True, null=True)),
                ('country', models.CharField(default='', max_length=2)),
                ('ua', models.CharField(default='', max_length=200)),
                ('device_type', models.CharField(default='', max_length=10)),
                ('destination_url', models.CharField(default='', max_length=1024)),
                ('sub1', models.CharField(default='', max_length=500)),
                ('sub2', models.CharField(default='', max_length=500)),
                ('affiliate', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='smart_link_clicks',
                    to=settings.AUTH_USER_MODEL,
                )),
                ('smart_link', models.ForeignKey(
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='clicks',
                    to='smartlinks.smartlink',
                )),
            ],
            options={
                'ordering': ('-created_at',),
            },
        ),
    ]
