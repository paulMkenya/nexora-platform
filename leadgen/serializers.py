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

from .models import AffiliatePostbackConfig, Lead

_PHONE_RE = re.compile(r'^\+?[0-9]{7,15}$')
_LANGUAGE_RE = re.compile(r'^[A-Za-z]{2,3}([-_][A-Za-z0-9]{2,8})?$')
_EXTRA_KEY_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,39}$')

# The canonical attribution keys, in the order they are written to
# Lead.attribution. Channel-neutral names deliberately: a buyer's own dialect
# (TrackBox's so/ad/term/campaign/medium) is a MAPPING concern, resolved per
# buyer by LeadBuyer.field_mapping, never a name we adopt at intake.
ATTRIBUTION_FIELDS = ('funnel', 'campaign', 'medium', 'term', 'ad')
SUB_FIELDS = ('sub1', 'sub2', 'sub3', 'sub4', 'sub5')

# Bounds on the `extra` escape hatch. Small on purpose: `extra` exists so a
# source can fill a buyer field Nexora has no name for (TrackBox MPC_6..12,
# say) without waiting on a migration — it is not a place to park a CRM
# record, and an unbounded dict on a public endpoint is a storage-amplification
# vector.
EXTRA_MAX_KEYS = 20
EXTRA_MAX_VALUE_LENGTH = 255

_RESERVED_EXTRA_KEYS = frozenset(ATTRIBUTION_FIELDS + SUB_FIELDS)


def build_attribution(data):
    """The Lead.attribution dict for one validated submission.

    Empty values are dropped rather than stored as '' — `attribution` is
    consulted with .get(), and a stored empty string would be forwarded by a
    connector as a real (blank) value, which some boxes treat differently
    from an absent key.
    """
    attribution = {}
    for name in ATTRIBUTION_FIELDS + SUB_FIELDS:
        value = (data.get(name) or '').strip()
        if value:
            attribution[name] = value
    for key, value in (data.get('extra') or {}).items():
        value = (value or '').strip()
        if value:
            attribution[key] = value
    return attribution


class LeadSubmitSerializer(serializers.Serializer):
    """The fields BOTH intake channels share.

    The attribution block below is on the base rather than the affiliate
    subclass because it is channel-neutral: a Nexora-hosted landing page has
    its own utm_* query string, and a lead that arrived from a Facebook
    campaign has a campaign whether an affiliate submitted it or not.
    sub1..sub5 and `extra` stay on the affiliate subclass — those are an
    affiliate's own tracking slots, meaningless on a hosted funnel.
    """
    first_name = serializers.CharField(max_length=120, required=False, allow_blank=True, default='')
    last_name = serializers.CharField(max_length=120, required=False, allow_blank=True, default='')
    email = serializers.EmailField(max_length=250)
    phone = serializers.CharField(max_length=32)
    vertical = serializers.CharField(
        max_length=120, required=False, allow_blank=True, default='',
        help_text=(
            'Your own classification of the lead (e.g. "crypto"). Some buyer integrations use it '
            'as the funnel/campaign label in their own reporting, so send a stable value or leave '
            'it out entirely -- never a per-lead unique string.'
        ),
    )
    source_id = serializers.CharField(max_length=120, required=False, allow_blank=True, default='')
    language = serializers.CharField(
        max_length=8, required=False, allow_blank=True, default='',
        help_text=(
            'The consumer language as ISO 639-1 (EN, DE, ES). Buyers that receive it route '
            'call-centre capacity on it, so send it when you know it -- whether a given offer '
            'forwards it depends on that integration. Omitted means unknown; Nexora never '
            'guesses one.'
        ),
    )
    funnel = serializers.CharField(
        max_length=120, required=False, allow_blank=True, default='',
        help_text=(
            'The funnel or traffic-source name this lead came through. Where the offer integration '
            'forwards it, it appears in the buyer own reporting, which is what they optimise on -- '
            'so send a real per-funnel value rather than one constant for all your traffic. It is '
            'recorded on the lead and reportable here either way.'
        ),
    )
    campaign = serializers.CharField(max_length=120, required=False, allow_blank=True, default='')
    medium = serializers.CharField(max_length=120, required=False, allow_blank=True, default='')
    term = serializers.CharField(max_length=120, required=False, allow_blank=True, default='')
    ad = serializers.CharField(max_length=120, required=False, allow_blank=True, default='')

    def validate_phone(self, value):
        cleaned = value.strip()
        if not _PHONE_RE.match(cleaned):
            raise serializers.ValidationError(
                'Enter a valid phone number (digits, optionally with a leading +).')
        return cleaned

    def validate_language(self, value):
        cleaned = value.strip()
        if cleaned and not _LANGUAGE_RE.match(cleaned):
            raise serializers.ValidationError(
                'Enter a language as ISO 639-1, optionally with a region (e.g. EN or en-GB).')
        # Upper-cased on the way in, so 'en', 'EN' and 'En' are one value in
        # reporting and one value on the wire. Boxes in this vertical
        # document the upper form (TrackBox: "lg": "EN").
        return cleaned.upper()


class AffiliateLeadSubmitSerializer(LeadSubmitSerializer):
    """The affiliate-facing inbound contract — Affiliate Inbound API spec
    §4.3. offer_id is mandatory here (and ONLY here — the base serializer
    stays optional-offer for the landing-page channel, which supplies its
    offer from the URL instead). country/ip/user_agent/sub1..sub5 are all
    optional passthrough/enrichment fields; sub1..sub5 have no dedicated
    Lead columns — they ride in Lead.attribution and are echoed back by
    LeadOutSerializer from there, same as every other field already does."""
    offer_id = serializers.IntegerField()
    country = serializers.CharField(
        max_length=2, required=False, allow_blank=True, default='',
        help_text=(
            'ISO 3166-1 alpha-2 (e.g. US). Send it whenever you know the consumer country. SOME '
            'OFFERS REQUIRE IT -- the buyer they route to rejects a lead with no country -- and '
            'those offers are flagged under "Offers you can send to"; submitting to one without '
            'it returns 400 naming this field. Do not rely on Nexora deriving it from ip: that '
            'fallback is best-effort and often unavailable.'
        ),
    )
    ip = serializers.IPAddressField(
        required=False, allow_blank=True, default='',
        help_text=(
            'The consumer real IP -- the address their browser or app connected from. '
            'NOT your own server IP, and not a proxy in front of it. '
            'Send it: the buyer receives this value and checks it against the country you '
            'declare, so a missing or mismatched IP lowers the quality score on your traffic. '
            'If you genuinely do not have it, leave it out entirely -- we send nothing rather '
            'than substituting an address, because a wrong IP reads as fraud where an absent '
            'one only reads as unknown.'
        ),
    )
    user_agent = serializers.CharField(max_length=500, required=False, allow_blank=True, default='')
    sub1 = serializers.CharField(max_length=120, required=False, allow_blank=True, default='')
    sub2 = serializers.CharField(max_length=120, required=False, allow_blank=True, default='')
    sub3 = serializers.CharField(max_length=120, required=False, allow_blank=True, default='')
    sub4 = serializers.CharField(max_length=120, required=False, allow_blank=True, default='')
    sub5 = serializers.CharField(max_length=120, required=False, allow_blank=True, default='')
    extra = serializers.DictField(
        child=serializers.CharField(max_length=EXTRA_MAX_VALUE_LENGTH, allow_blank=True),
        required=False, default=dict,
        help_text=(
            f'Free key/value passthrough for a buyer field Nexora has no name of its own for -- at '
            f'most {EXTRA_MAX_KEYS} keys. Whether any of it reaches a buyer depends on that buyer '
            f'mapping being configured for the key, so agree the key names with your account '
            f'manager first rather than inventing them. Use the named fields above where one fits: '
            f'only those are validated and reportable.'
        ),
    )

    def validate_country(self, value):
        return value.strip().upper()

    def validate_extra(self, value):
        if len(value) > EXTRA_MAX_KEYS:
            raise serializers.ValidationError(f'At most {EXTRA_MAX_KEYS} keys.')
        for key in value:
            if key in _RESERVED_EXTRA_KEYS:
                # Silently letting `extra` shadow a named field would make
                # two different requests that look equivalent behave
                # differently, depending on which one build_attribution
                # happened to write last.
                raise serializers.ValidationError(
                    f'"{key}" is a named field — send it at the top level, not inside extra.')
            if not _EXTRA_KEY_RE.match(key):
                raise serializers.ValidationError(
                    f'"{key}" is not a usable key: letters, digits, "_", "." and "-" only, '
                    f'40 characters maximum.')
        return value


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
            'buyer_status', 'buyer_status_updated_at', 'country', 'language',
            'attribution',
            'sub1', 'sub2', 'sub3', 'sub4', 'sub5', 'created_at', 'updated_at',
        ]
        read_only_fields = fields

    def _sub(self, obj, key):
        """attribution first, raw_payload second.

        The fallback is not dead code: sub1..sub5 lived in raw_payload before
        Lead.attribution existed, and every lead submitted up to that
        migration still carries them there. Reading both keeps an affiliate's
        historical leads echoing the same values they always did — this
        serializer backs GET /api/leads, which affiliates reconcile against.
        """
        attribution = obj.attribution or {}
        if key in attribution:
            return attribution[key]
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


# --- postback self-service (spec §5.1, over the API rather than the portal) ---

class PostbackConfigSerializer(serializers.ModelSerializer):
    """An affiliate's own postback registration.

    NOTE WHAT IS ABSENT: `secret`. It is an HMAC signing credential and is
    readable exactly once, in the create response — the same show-once contract
    public_api.APIKey and the portal already use. Putting it on the list/detail
    representation would mean every GET, every log line and every proxy cache
    that ever touched one carries a live credential. `secret_set` reports that
    one exists without disclosing it.

    `affiliate` is absent for a different reason: it is never client-supplied.
    The view takes it from the authenticated key, so accepting it here would
    invite a request that looks like it can register a postback for someone
    else.
    """
    secret_set = serializers.SerializerMethodField()

    class Meta:
        model = AffiliatePostbackConfig
        fields = ('id', 'url', 'subscribed_statuses', 'is_active',
                  'secret_set', 'created_at', 'updated_at')
        read_only_fields = ('id', 'secret_set', 'created_at', 'updated_at')

    def get_secret_set(self, obj):
        return bool(obj.secret)

    def validate_url(self, value):
        """SSRF guard — leadgen/security.py's fourth call site, and the reason
        this cannot just be a plain ModelSerializer. An approved affiliate is
        still an external party: without this they could point our own worker
        at an internal service and read the outcome back out of the delivery
        log. Raised as a DRF field error so the caller gets 400 + a message
        naming the field, not a 500 from an uncaught ValueError."""
        from .security import UnsafePostbackURLError, validate_postback_url

        value = (value or '').strip()
        try:
            validate_postback_url(value)
        except UnsafePostbackURLError as exc:
            raise serializers.ValidationError(str(exc))
        return value

    def validate_subscribed_statuses(self, value):
        """Empty means EVERY status fires — deliberately the opposite of
        public_api.WebhookEndpoint's convention, and the model documents why.
        An unknown status here is almost always a typo that would silently
        never fire, so it is rejected rather than stored."""
        from . import canonical_status

        if not isinstance(value, list):
            raise serializers.ValidationError('Must be a list of canonical status values.')
        unknown = [v for v in value if v not in canonical_status.VALUES]
        if unknown:
            raise serializers.ValidationError(
                f'Unknown status(es): {", ".join(map(str, unknown))}. '
                f'Pull the full vocabulary from GET /api/leads/statuses.')
        return value
