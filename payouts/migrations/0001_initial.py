from decimal import Decimal
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
            name='PayoutMethod',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('method', models.CharField(choices=[('paypal', 'PayPal'), ('wise', 'Wise'), ('paxum', 'Paxum'), ('mpesa', 'M-Pesa'), ('bank', 'Bank Transfer'), ('crypto', 'Cryptocurrency')], max_length=10)),
                ('details', models.JSONField(blank=True, default=dict)),
                ('is_default', models.BooleanField(default=False)),
                ('verified', models.BooleanField(default=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('affiliate', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='payout_methods', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ('-is_default', 'created_at'),
            },
        ),
        migrations.CreateModel(
            name='PayoutRequest',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('amount', models.DecimalField(decimal_places=2, max_digits=12)),
                ('currency', models.CharField(default='USD', max_length=10)),
                ('method', models.CharField(choices=[('paypal', 'PayPal'), ('wise', 'Wise'), ('paxum', 'Paxum'), ('mpesa', 'M-Pesa'), ('bank', 'Bank Transfer'), ('crypto', 'Cryptocurrency')], default='paypal', max_length=10)),
                ('status', models.CharField(choices=[('pending', 'Pending'), ('approved', 'Approved'), ('processing', 'Processing'), ('paid', 'Paid'), ('failed', 'Failed')], default='pending', max_length=12)),
                ('scheduled_for', models.DateField(blank=True, null=True)),
                ('paid_at', models.DateTimeField(blank=True, null=True)),
                ('tx_ref', models.CharField(blank=True, db_index=True, default='', max_length=255)),
                ('period_start', models.DateField(blank=True, null=True)),
                ('period_end', models.DateField(blank=True, null=True)),
                ('notes', models.TextField(blank=True, default='')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('affiliate', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='payout_requests', to=settings.AUTH_USER_MODEL)),
                ('payout_method', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='requests', to='payouts.payoutmethod')),
            ],
            options={
                'ordering': ('-created_at',),
            },
        ),
        migrations.CreateModel(
            name='PayoutBatch',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('provider', models.CharField(choices=[('paypal', 'PayPal'), ('wise', 'Wise'), ('paxum', 'Paxum'), ('mpesa', 'M-Pesa'), ('bank', 'Bank Transfer'), ('crypto', 'Cryptocurrency')], max_length=10)),
                ('total', models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=14)),
                ('csv_export', models.TextField(blank=True, default='')),
                ('notes', models.TextField(blank=True, default='')),
                ('requests', models.ManyToManyField(blank=True, related_name='batches', to='payouts.payoutrequest')),
            ],
            options={
                'ordering': ('-created_at',),
            },
        ),
        migrations.CreateModel(
            name='PayoutSettings',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('min_threshold', models.DecimalField(decimal_places=2, default=Decimal('50.00'), max_digits=10)),
                ('schedule', models.CharField(choices=[('weekly', 'Weekly'), ('biweekly', 'Bi-weekly'), ('monthly', 'Monthly')], default='monthly', max_length=10)),
                ('net_terms', models.PositiveSmallIntegerField(default=15, help_text='Net days before payout')),
                ('paid_through', models.DateField(blank=True, null=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('affiliate', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='payout_settings', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name_plural': 'Payout settings',
            },
        ),
        migrations.AddConstraint(
            model_name='payoutrequest',
            constraint=models.UniqueConstraint(condition=models.Q(tx_ref__gt=''), fields=['tx_ref'], name='payouts_request_unique_tx_ref'),
        ),
        migrations.AddConstraint(
            model_name='payoutmethod',
            constraint=models.UniqueConstraint(fields=['affiliate', 'method', 'details'], name='payouts_method_unique_affiliate_method_details'),
        ),
    ]
