from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tracker', '0014_inboundpostbacklog'),
    ]

    operations = [
        # Click fraud fields
        migrations.AddField(
            model_name='click',
            name='fraud_score',
            field=models.IntegerField(default=0),
        ),
        migrations.AddField(
            model_name='click',
            name='fraud_reasons',
            field=models.JSONField(default=list, blank=True),
        ),
        migrations.AddField(
            model_name='click',
            name='is_proxy',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='click',
            name='is_datacenter',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='click',
            name='is_bot',
            field=models.BooleanField(default=False),
        ),
        # Conversion fraud fields
        migrations.AddField(
            model_name='conversion',
            name='fraud_score',
            field=models.IntegerField(default=0),
        ),
        migrations.AddField(
            model_name='conversion',
            name='fraud_reasons',
            field=models.JSONField(default=list, blank=True),
        ),
        migrations.AddField(
            model_name='conversion',
            name='auto_rejected_reason',
            field=models.CharField(max_length=128, default='', blank=True),
        ),
    ]
