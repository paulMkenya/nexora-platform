"""
Unmanaged Django models backed by Postgres materialized views.

Django will not CREATE or ALTER these tables — the views are managed by
reporting/migrations/0001_reporting_matviews.py via RunSQL.

The 'id' column in each view is ROW_NUMBER() OVER (...), which gives a stable
sort handle within a single matview snapshot. It changes on each REFRESH, so
never use it as a durable reference key — use period + dimension fields instead.
"""
from django.db import models


class ClickHourlyStats(models.Model):
    period = models.DateTimeField()
    brand_id = models.BigIntegerField()
    offer_id = models.BigIntegerField(null=True)
    affiliate_id = models.BigIntegerField(null=True)
    country = models.CharField(max_length=2)
    traffic_source = models.CharField(max_length=500)
    device_type = models.CharField(max_length=10)
    clicks = models.BigIntegerField()
    revenue = models.DecimalField(max_digits=20, decimal_places=2)
    payout = models.DecimalField(max_digits=20, decimal_places=2)
    avg_fraud_score = models.FloatField(null=True)

    class Meta:
        managed = False
        db_table = 'reporting_click_hourly'


class ClickDailyStats(models.Model):
    period = models.DateTimeField()
    brand_id = models.BigIntegerField()
    offer_id = models.BigIntegerField(null=True)
    affiliate_id = models.BigIntegerField(null=True)
    country = models.CharField(max_length=2)
    traffic_source = models.CharField(max_length=500)
    device_type = models.CharField(max_length=10)
    clicks = models.BigIntegerField()
    revenue = models.DecimalField(max_digits=20, decimal_places=2)
    payout = models.DecimalField(max_digits=20, decimal_places=2)
    avg_fraud_score = models.FloatField(null=True)

    class Meta:
        managed = False
        db_table = 'reporting_click_daily'


class ConversionHourlyStats(models.Model):
    period = models.DateTimeField()
    brand_id = models.BigIntegerField()
    offer_id = models.BigIntegerField(null=True)
    affiliate_id = models.BigIntegerField(null=True)
    country = models.CharField(max_length=2)
    traffic_source = models.CharField(max_length=500)
    device_type = models.CharField(max_length=10)
    conversions_total = models.BigIntegerField()
    conversions_approved = models.BigIntegerField()
    conversions_rejected = models.BigIntegerField()
    conversions_hold = models.BigIntegerField()
    revenue = models.DecimalField(max_digits=20, decimal_places=2)
    payout = models.DecimalField(max_digits=20, decimal_places=2)

    class Meta:
        managed = False
        db_table = 'reporting_conversion_hourly'


class ConversionDailyStats(models.Model):
    period = models.DateTimeField()
    brand_id = models.BigIntegerField()
    offer_id = models.BigIntegerField(null=True)
    affiliate_id = models.BigIntegerField(null=True)
    country = models.CharField(max_length=2)
    traffic_source = models.CharField(max_length=500)
    device_type = models.CharField(max_length=10)
    conversions_total = models.BigIntegerField()
    conversions_approved = models.BigIntegerField()
    conversions_rejected = models.BigIntegerField()
    conversions_hold = models.BigIntegerField()
    revenue = models.DecimalField(max_digits=20, decimal_places=2)
    payout = models.DecimalField(max_digits=20, decimal_places=2)

    class Meta:
        managed = False
        db_table = 'reporting_conversion_daily'
