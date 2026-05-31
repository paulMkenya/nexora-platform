from rest_framework import serializers


class ClicksReportSerializer(serializers.Serializer):
    period = serializers.DateTimeField(required=False, allow_null=True)
    brand_id = serializers.IntegerField(required=False, allow_null=True)
    offer_id = serializers.IntegerField(required=False, allow_null=True)
    affiliate_id = serializers.IntegerField(required=False, allow_null=True)
    country = serializers.CharField(required=False, allow_null=True)
    traffic_source = serializers.CharField(required=False, allow_null=True)
    device_type = serializers.CharField(required=False, allow_null=True)
    clicks = serializers.IntegerField()
    revenue = serializers.DecimalField(max_digits=20, decimal_places=2, required=False, allow_null=True)
    payout = serializers.DecimalField(max_digits=20, decimal_places=2, required=False, allow_null=True)
    avg_fraud_score = serializers.FloatField(required=False, allow_null=True)


class ConversionsReportSerializer(serializers.Serializer):
    period = serializers.DateTimeField(required=False, allow_null=True)
    brand_id = serializers.IntegerField(required=False, allow_null=True)
    offer_id = serializers.IntegerField(required=False, allow_null=True)
    affiliate_id = serializers.IntegerField(required=False, allow_null=True)
    country = serializers.CharField(required=False, allow_null=True)
    traffic_source = serializers.CharField(required=False, allow_null=True)
    device_type = serializers.CharField(required=False, allow_null=True)
    conversions_total = serializers.IntegerField()
    conversions_approved = serializers.IntegerField()
    conversions_rejected = serializers.IntegerField()
    conversions_hold = serializers.IntegerField()
    revenue = serializers.DecimalField(max_digits=20, decimal_places=2, required=False, allow_null=True)
    payout = serializers.DecimalField(max_digits=20, decimal_places=2, required=False, allow_null=True)


class RevenueReportSerializer(serializers.Serializer):
    period = serializers.DateTimeField(required=False, allow_null=True)
    brand_id = serializers.IntegerField(required=False, allow_null=True)
    offer_id = serializers.IntegerField(required=False, allow_null=True)
    affiliate_id = serializers.IntegerField(required=False, allow_null=True)
    country = serializers.CharField(required=False, allow_null=True)
    traffic_source = serializers.CharField(required=False, allow_null=True)
    device_type = serializers.CharField(required=False, allow_null=True)
    clicks = serializers.IntegerField(required=False, allow_null=True)
    conversions = serializers.IntegerField(required=False, allow_null=True)
    total_revenue = serializers.FloatField(required=False, allow_null=True)
    total_payout = serializers.FloatField(required=False, allow_null=True)
    epc = serializers.FloatField(required=False, allow_null=True)
    cr_pct = serializers.FloatField(required=False, allow_null=True)
