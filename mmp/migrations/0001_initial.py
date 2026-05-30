from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('offer', '0023_advertiserpostbackkey'),
    ]

    operations = [
        migrations.CreateModel(
            name='MMP',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=64)),
                ('vendor', models.CharField(choices=[
                    ('appsflyer', 'AppsFlyer'),
                    ('adjust', 'Adjust'),
                    ('branch', 'Branch'),
                    ('singular', 'Singular'),
                    ('kochava', 'Kochava'),
                ], max_length=20, unique=True)),
                ('click_template', models.CharField(default='', max_length=1024)),
                ('callback_patterns', models.JSONField(blank=True, default=dict)),
                ('required_macros', models.JSONField(blank=True, default=list)),
            ],
            options={
                'verbose_name': 'MMP',
                'verbose_name_plural': 'MMPs',
            },
        ),
        migrations.CreateModel(
            name='MMPCallback',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('vendor', models.CharField(choices=[
                    ('appsflyer', 'AppsFlyer'),
                    ('adjust', 'Adjust'),
                    ('branch', 'Branch'),
                    ('singular', 'Singular'),
                    ('kochava', 'Kochava'),
                ], db_index=True, max_length=20)),
                ('click_id', models.CharField(db_index=True, max_length=64)),
                ('event_name', models.CharField(default='', max_length=128)),
                ('raw_data', models.JSONField(blank=True, default=dict)),
                ('processed', models.BooleanField(default=False)),
                ('offer', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='mmp_callbacks',
                    to='offer.offer',
                )),
            ],
            options={
                'ordering': ('-created_at',),
            },
        ),
        migrations.AddConstraint(
            model_name='mmpcallback',
            constraint=models.UniqueConstraint(
                fields=['click_id', 'event_name'],
                name='mmp_callback_unique_click_event',
            ),
        ),
    ]
