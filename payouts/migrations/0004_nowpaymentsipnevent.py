from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('payouts', '0003_cryptopayoutbatch_payoutrequest_provider_status_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='NowPaymentsIPNEvent',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('provider', models.CharField(default='nowpayments', max_length=32)),
                ('withdrawal_id', models.CharField(max_length=64)),
                ('status', models.CharField(max_length=32)),
                ('raw', models.JSONField(blank=True, default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'ordering': ('-created_at',),
            },
        ),
        migrations.AddConstraint(
            model_name='nowpaymentsipnevent',
            constraint=models.UniqueConstraint(fields=('provider', 'withdrawal_id', 'status'), name='payouts_nowpayments_ipn_unique_event'),
        ),
    ]
