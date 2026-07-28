"""DRF serializers for the inbound lead-submission API.

Validation mirrors the industry-standard lead-buyer contract shape (phone +
email required, names optional, sane max lengths) — the same fields
affiliates already expect from platforms like op-brandy.com, so integrating
with Nexora's inbound API should feel familiar rather than bespoke.
"""
import re

from rest_framework import serializers

from .models import Lead

_PHONE_RE = re.compile(r'^\+?[0-9]{7,15}$')


class LeadSubmitSerializer(serializers.Serializer):
    first_name = serializers.CharField(max_length=120, required=False, allow_blank=True, default='')
    last_name = serializers.CharField(max_length=120, required=False, allow_blank=True, default='')
    email = serializers.EmailField(max_length=250)
    phone = serializers.CharField(max_length=32)
    vertical = serializers.CharField(max_length=120, required=False, allow_blank=True, default='')
    source_id = serializers.CharField(max_length=120, required=False, allow_blank=True, default='')

    def validate_phone(self, value):
        cleaned = value.strip()
        if not _PHONE_RE.match(cleaned):
            raise serializers.ValidationError(
                'Enter a valid phone number (digits, optionally with a leading +).')
        return cleaned


class LeadOutSerializer(serializers.ModelSerializer):
    class Meta:
        model = Lead
        fields = [
            'id', 'first_name', 'last_name', 'email', 'phone', 'vertical',
            'source_id', 'status', 'deposit', 'created_at',
        ]
        read_only_fields = fields
