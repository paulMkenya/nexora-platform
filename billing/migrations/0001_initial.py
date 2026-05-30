from decimal import Decimal
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('offer', '0024_offer_mmp_fields'),
    ]

    operations = [
        migrations.CreateModel(
            name='AdvertiserWallet',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('balance', models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=12)),
                ('currency', models.CharField(default='USD', max_length=3)),
                ('credit_limit', models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=12)),
                ('low_balance_threshold', models.DecimalField(decimal_places=2, default=Decimal('10.00'), max_digits=12)),
                ('low_balance_alert_sent', models.BooleanField(default=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('advertiser', models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='wallet',
                    to='offer.advertiser',
                )),
            ],
            options={'verbose_name': 'Advertiser Wallet'},
        ),
        migrations.CreateModel(
            name='WalletTopUp',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('amount', models.DecimalField(decimal_places=2, max_digits=12)),
                ('provider', models.CharField(choices=[
                    ('stripe', 'Stripe'), ('paystack', 'Paystack'), ('manual', 'Manual')
                ], max_length=20)),
                ('status', models.CharField(choices=[
                    ('pending', 'Pending'), ('completed', 'Completed'), ('failed', 'Failed')
                ], default='pending', max_length=20)),
                ('external_ref', models.CharField(blank=True, db_index=True, default='', max_length=255)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('wallet', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='topups',
                    to='billing.advertiserwallet',
                )),
            ],
            options={'ordering': ('-created_at',)},
        ),
        migrations.CreateModel(
            name='WalletTransaction',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('type', models.CharField(choices=[
                    ('topup', 'Top-up'), ('debit', 'Debit'),
                    ('refund', 'Refund'), ('adjustment', 'Adjustment')
                ], max_length=20)),
                ('amount', models.DecimalField(decimal_places=2, max_digits=12)),
                ('balance_after', models.DecimalField(decimal_places=2, max_digits=12)),
                ('description', models.CharField(blank=True, default='', max_length=255)),
                ('reference', models.CharField(blank=True, db_index=True, default='', max_length=128)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('wallet', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='transactions',
                    to='billing.advertiserwallet',
                )),
            ],
            options={'ordering': ('-created_at',)},
        ),
        migrations.AddConstraint(
            model_name='wallettransaction',
            constraint=models.UniqueConstraint(
                condition=models.Q(reference__gt=''),
                fields=['reference'],
                name='billing_txn_unique_reference',
            ),
        ),
        migrations.CreateModel(
            name='Invoice',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('period_start', models.DateField()),
                ('period_end', models.DateField()),
                ('subtotal', models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=12)),
                ('vat_rate', models.DecimalField(decimal_places=2, default=Decimal('16.00'), max_digits=5)),
                ('vat_amount', models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=12)),
                ('total', models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=12)),
                ('status', models.CharField(choices=[
                    ('draft', 'Draft'), ('sent', 'Sent'), ('paid', 'Paid')
                ], default='draft', max_length=20)),
                ('pdf_url', models.CharField(blank=True, default='', max_length=512)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('wallet', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='invoices',
                    to='billing.advertiserwallet',
                )),
            ],
            options={'ordering': ('-period_start',)},
        ),
        migrations.AddConstraint(
            model_name='invoice',
            constraint=models.UniqueConstraint(
                fields=['wallet', 'period_start'],
                name='billing_invoice_unique_wallet_period',
            ),
        ),
    ]
