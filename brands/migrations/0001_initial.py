from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name='Brand',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('slug', models.SlugField(max_length=60, unique=True)),
                ('name', models.CharField(max_length=128)),
                ('primary_domain', models.CharField(max_length=253, unique=True)),
                ('tracking_domain', models.CharField(max_length=253, unique=True)),
                ('logo', models.CharField(blank=True, default='', max_length=500)),
                ('favicon', models.CharField(blank=True, default='', max_length=500)),
                ('primary_color', models.CharField(default='#6366f1', max_length=7)),
                ('secondary_color', models.CharField(default='#4f46e5', max_length=7)),
                ('support_email', models.EmailField(default='', max_length=254)),
                ('terms_url', models.CharField(blank=True, default='', max_length=500)),
                ('privacy_url', models.CharField(blank=True, default='', max_length=500)),
                ('is_default', models.BooleanField(default=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={'ordering': ('name',)},
        ),
    ]
