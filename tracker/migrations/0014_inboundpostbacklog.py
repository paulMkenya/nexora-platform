from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('offer', '0023_advertiserpostbackkey'),
        ('tracker', '0013_auto_20201018_0101'),
    ]

    operations = [
        migrations.CreateModel(
            name='InboundPostbackLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('received_at', models.DateTimeField(auto_now_add=True)),
                ('click_id', models.CharField(default='', max_length=64)),
                ('status_param', models.CharField(default='', max_length=20)),
                ('sum_param', models.CharField(default='', max_length=32)),
                ('query_string', models.CharField(default='', max_length=1000)),
                ('hmac_status', models.CharField(
                    choices=[
                        ('ok',      'OK — signature matched'),
                        ('fail',    'Fail — signature mismatch'),
                        ('missing', 'Missing — no sig param'),
                        ('skip',    'Skip — no key registered or flag off'),
                    ],
                    default='skip',
                    max_length=10,
                )),
                ('response_code', models.IntegerField(default=200)),
                ('note', models.CharField(blank=True, default='', max_length=255)),
                ('advertiser', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='inbound_postback_logs',
                    to='offer.advertiser',
                )),
            ],
            options={'ordering': ('-received_at',)},
        ),
    ]
