"""DRF serializers for the inbound lead-submission API.

Validation mirrors the industry-standard lead-buyer contract shape (phone +
email required, names optional, sane max lengths) — the same fields
affiliates already expect from platforms like op-brandy.com, so integrating
with Nexora's inbound API should feel familiar rather than bespoke.

LeadSubmitSerializer is shared by BOTH intake channels (public_views.py's
landing-page capture, and AffiliateLeadSubmitSerializer below) — it stays
exactly as it was so the landing-page path (which never supplies offer_id;
it already knows its offer from the URL) keeps working unchanged.
AffiliateLeadSubmitSerializer subclasses it to add the fields that are
meaningful only for the affiliate channel (Affiliate Inbound API spec §4.3).
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


class AffiliateLeadSubmitSerializer(LeadSubmitSerializer):
    """The affiliate-facing inbound contract — Affiliate Inbound API spec
    §4.3. offer_id is mandatory here (and ONLY here — the base serializer
    stays optional-offer for the landing-page channel, which supplies its
    offer from the URL instead). country/ip/user_agent/sub1..sub5 are all
    optional passthrough/enrichment fields; sub1..sub5 have no dedicated
    Lead columns — they ride in Lead.raw_payload and are echoed back by
    LeadOutSerializer from there, same as every other field already does."""
    offer_id = serializers.IntegerField()
    country = serializers.CharField(max_length=2, required=False, allow_blank=True, default='')
    ip = serializers.IPAddressField(required=False, allow_blank=True, default='')
    user_agent = serializers.CharField(max_length=500, required=False, allow_blank=True, default='')
    sub1 = serializers.CharField(max_length=120, required=False, allow_blank=True, default='')
    sub2 = serializers.CharField(max_length=120, required=False, allow_blank=True, default='')
    sub3 = serializers.CharField(max_length=120, required=False, allow_blank=True, default='')
    sub4 = serializers.CharField(max_length=120, required=False, allow_blank=True, default='')
    sub5 = serializers.CharField(max_length=120, required=False, allow_blank=True, default='')

    def validate_country(self, value):
        return value.strip().upper()


class LeadOutSerializer(serializers.ModelSerializer):
    canonical_status = serializers.CharField(read_only=True)
    country = serializers.CharField(source='country_iso2', read_only=True)
    sub1 = serializers.SerializerMethodField()
    sub2 = serializers.SerializerMethodField()
    sub3 = serializers.SerializerMethodField()
    sub4 = serializers.SerializerMethodField()
    sub5 = serializers.SerializerMethodField()

    class Meta:
        model = Lead
        fields = [
            'id', 'first_name', 'last_name', 'email', 'phone', 'vertical',
            'source_id', 'status', 'canonical_status', 'deposit',
            'buyer_status', 'buyer_status_updated_at', 'country',
            'sub1', 'sub2', 'sub3', 'sub4', 'sub5', 'created_at', 'updated_at',
        ]
        read_only_fields = fields

    def _sub(self, obj, key):
        return (obj.raw_payload or {}).get(key, '')

    def get_sub1(self, obj):
        return self._sub(obj, 'sub1')

    def get_sub2(self, obj):
        return self._sub(obj, 'sub2')

    def get_sub3(self, obj):
        return self._sub(obj, 'sub3')

    def get_sub4(self, obj):
        return self._sub(obj, 'sub4')

    def get_sub5(self, obj):
        return self._sub(obj, 'sub5')


class LeadStatusEventOutSerializer(serializers.Serializer):
    to_status = serializers.CharField()
    lead_seq = serializers.IntegerField()
    source = serializers.CharField()
    created_at = serializers.DateTimeField()


class LeadDetailOutSerializer(LeadOutSerializer):
    """GET /api/leads/<id> only (spec §5.2: "current status + full or recent
    status timeline"). Deliberately NOT on the plain LeadOutSerializer used
    by list/submit — a paginated list of 50 leads would otherwise run 50
    extra timeline queries for data most pull-API callers don't need."""
    status_timeline = serializers.SerializerMethodField()

    class Meta(LeadOutSerializer.Meta):
        fields = LeadOutSerializer.Meta.fields + ['status_timeline']
        read_only_fields = fields

    def get_status_timeline(self, obj):
        # Only APPLIED events — a recorded-but-not-applied TESTING-phase
        # buyer status is internal authority-engine bookkeeping, never
        # something the affiliate should see as if it were real.
        events = obj.status_events.filter(applied=True).order_by('created_at')
        return LeadStatusEventOutSerializer(events, many=True).data
