from rest_framework import serializers

from offer.models import Advertiser, Offer
from tracker.models import Conversion

from .models import APIKey, WebhookDelivery, WebhookEndpoint


# ── Auth ─────────────────────────────────────────────────────────────────────

class TokenRequestSerializer(serializers.Serializer):
    grant_type = serializers.ChoiceField(choices=['client_credentials'])
    client_id = serializers.UUIDField()
    client_secret = serializers.CharField()


class TokenResponseSerializer(serializers.Serializer):
    access_token = serializers.CharField()
    token_type = serializers.CharField()
    expires_in = serializers.IntegerField()


class APIKeyCreateSerializer(serializers.ModelSerializer):
    secret = serializers.CharField(read_only=True)
    client_id = serializers.UUIDField(read_only=True)

    class Meta:
        model = APIKey
        fields = ('id', 'client_id', 'secret', 'name', 'requests_per_hour', 'created_at')
        read_only_fields = ('id', 'client_id', 'secret', 'created_at')


class APIKeyListSerializer(serializers.ModelSerializer):
    """Used for list endpoint — omits secret."""

    class Meta:
        model = APIKey
        fields = ('id', 'client_id', 'name', 'requests_per_hour', 'is_active', 'last_used_at', 'created_at')


# ── Advertiser API ───────────────────────────────────────────────────────────

class AdvertiserOfferSerializer(serializers.ModelSerializer):
    class Meta:
        model = Offer
        fields = (
            'id', 'title', 'description', 'tracking_link', 'preview_link',
            'status', 'icon', 'advertiser', 'brand',
        )
        read_only_fields = ('brand',)


class AdvertiserConversionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Conversion
        fields = (
            'id', 'click_id', 'created_at', 'country', 'revenue', 'payout',
            'status', 'goal_value', 'offer', 'affiliate',
        )
        read_only_fields = ('id', 'click_id', 'created_at', 'offer', 'affiliate')


class BulkActionSerializer(serializers.Serializer):
    ids = serializers.ListField(child=serializers.UUIDField(), min_length=1, max_length=500)
    comment = serializers.CharField(required=False, allow_blank=True, default='')


class WalletSerializer(serializers.Serializer):
    balance = serializers.DecimalField(max_digits=12, decimal_places=2)
    currency = serializers.CharField()
    credit_limit = serializers.DecimalField(max_digits=12, decimal_places=2, required=False, allow_null=True)


# ── Network Admin API ────────────────────────────────────────────────────────

class AdminOfferSerializer(serializers.ModelSerializer):
    class Meta:
        model = Offer
        fields = '__all__'


class AdminConversionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Conversion
        fields = '__all__'


class AdminAdvertiserSerializer(serializers.ModelSerializer):
    class Meta:
        model = Advertiser
        fields = '__all__'


# ── Webhooks ─────────────────────────────────────────────────────────────────

class WebhookEndpointSerializer(serializers.ModelSerializer):
    class Meta:
        model = WebhookEndpoint
        fields = ('id', 'url', 'secret', 'events', 'is_active', 'created_at')
        read_only_fields = ('id', 'created_at')

    def validate_events(self, value):
        valid = {'offer.created', 'conversion.approved', 'payout.paid'}
        invalid = set(value) - valid
        if invalid:
            raise serializers.ValidationError(f'Unknown events: {invalid}. Valid: {valid}')
        return value


class WebhookDeliverySerializer(serializers.ModelSerializer):
    class Meta:
        model = WebhookDelivery
        fields = ('id', 'event', 'payload', 'status', 'attempts', 'last_error', 'created_at', 'delivered_at')
