"""leadgen — Nexora's consumer-lead capture + buyer-injection engine.

Two intake channels feed the same Lead store:
  1. Affiliate-submitted, via the inbound API (public_api.APIKey auth,
     see api_views.py) — affiliates who already generate leads through
     their own means submit them here.
  2. Nexora-hosted landing pages, for direct FB/Google ad traffic against
     an Offer's own funnel (see public_views.py).

Every Lead is then routed OUT to a configured LeadBuyer (see
connectors.py). Phase 4 of the lead-distribution build (the Box
Registry — see leadgen/README.md) split what used to be one flat LeadBuyer
config into two levels: BoxType is the reusable, platform-level template
(the same for every brand on that platform — op-brandy.com is BoxType #1);
LeadBuyer is the tenant instance — which BoxType it speaks, its own
base_url + encrypted API key, and field-name overrides on top of the
BoxType's defaults. Onboarding a new brand on a KNOWN box is a LeadBuyer
row, no code.
"""
from django.conf import settings
from django.db import models

from nexora.crypto import decrypt_secret, encrypt_secret


class BoxType(models.Model):
    """A reusable integration template — the parts of a lead-buying
    platform's API that are IDENTICAL for every brand/tenant using it
    (endpoint shape, auth scheme, rate-limit policy, the canonical field
    set). A LeadBuyer (the brand-specific instance) points at exactly one
    BoxType and supplies only what varies per brand: base_url, the
    encrypted API key, and field-name overrides. See leadgen/README.md's
    Box Registry section — "if onboarding brand #2 on the same platform
    requires editing anything other than a LeadBuyer row, the BoxType
    wasn't abstracted correctly" is the test for whether something belongs
    here or on LeadBuyer."""

    AUTH_API_KEY_QUERY = 'api_key_query'
    AUTH_API_KEY_HEADER = 'api_key_header'
    AUTH_BEARER = 'bearer'
    AUTH_CHOICES = [
        (AUTH_API_KEY_QUERY, 'API key in query string'),
        (AUTH_API_KEY_HEADER, 'API key in header'),
        (AUTH_BEARER, 'Bearer token'),
    ]

    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=60, unique=True)
    version = models.PositiveIntegerField(
        default=1,
        help_text='Bump when the platform changes its own API shape, so buyers on '
                   'an older version of this box do not silently start behaving '
                   'differently — a version bump is a signal to review them.',
    )
    description = models.TextField(blank=True, default='')

    # Declarative connector selection — a dotted Python path, resolved via
    # connectors.get_connector() using Django's own import_string (the same
    # safe mechanism behind AUTHENTICATION_BACKENDS/STORAGES/etc.), never
    # eval'd code. The generic LeadBuyerConnector handles the common REST +
    # API-key + JSON leads/batch shape; only a genuinely different platform
    # (a different auth scheme entirely, XML, SOAP, a different success/
    # duplicate/failure envelope) needs its own connector_class pointing at
    # a real Python subclass — see leadgen/README.md.
    connector_class = models.CharField(max_length=200, default='leadgen.connectors.LeadBuyerConnector')

    # --- endpoint shape (same for every buyer on this platform) ---
    auth_type = models.CharField(max_length=20, choices=AUTH_CHOICES, default=AUTH_API_KEY_QUERY)
    auth_param_name = models.CharField(max_length=60, default='apiKey')
    single_endpoint_path = models.CharField(max_length=200, default='/leads')
    batch_endpoint_path = models.CharField(max_length=200, blank=True, default='/leads/batch')
    fetch_endpoint_path = models.CharField(max_length=200, blank=True, default='/leads')
    deposits_endpoint_path = models.CharField(max_length=200, blank=True, default='')
    batch_max_size = models.PositiveIntegerField(default=1, help_text='1 disables batching.')

    # --- rate-limit policy (this platform's documented limits) ---
    rate_limit_burst = models.PositiveIntegerField(default=10)
    rate_limit_refill_tokens = models.PositiveIntegerField(default=1)
    rate_limit_refill_seconds = models.PositiveIntegerField(default=1)

    # --- canonical field set — the DEFAULT mapping every instance on this
    # platform starts from; a LeadBuyer overrides individual entries via
    # its own field_mapping (see LeadBuyer.get_effective_field_mapping) ---
    default_field_mapping = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('name',)

    def __str__(self):
        return f'{self.name} (v{self.version})'


class LeadBuyer(models.Model):
    """A configured outbound lead-buying partner — a BuyerInstance in the
    build guide's terms: which BoxType it speaks (box_type), plus only
    what varies per brand (base_url, the encrypted API key, field-mapping
    overrides, caps/priority/brand scope, its own auto_inject switch)."""

    box_type = models.ForeignKey(
        BoxType, on_delete=models.PROTECT, related_name='buyers', null=True, blank=False,
        help_text='Which platform template this buyer speaks. Nullable at the DB '
                   'level only so the Phase 4 migration stayed additive for the '
                   'buyer row(s) that predate the Box Registry; always set this.',
    )

    # --- Legacy fields (pre-Box-Registry). Superseded by box_type's
    # equivalents as of Phase 4 — the connector no longer reads these.
    # Left in place rather than dropped (no destructive migration); fine to
    # remove in a future pass once every buyer has a box_type. _LEGACY_FIELDS
    # is the single source of truth both forms.py (excludes them entirely)
    # and admin.py (keeps them readonly, for audit/debugging) key off of —
    # add/remove a legacy field here only, never duplicate the list.
    _LEGACY_FIELDS = (
        'auth_type', 'auth_param_name', 'single_endpoint_path', 'batch_endpoint_path',
        'fetch_endpoint_path', 'deposits_endpoint_path', 'batch_max_size',
        'rate_limit_burst', 'rate_limit_refill_tokens', 'rate_limit_refill_seconds',
    )

    AUTH_API_KEY_QUERY = 'api_key_query'
    AUTH_API_KEY_HEADER = 'api_key_header'
    AUTH_BEARER = 'bearer'
    AUTH_CHOICES = [
        (AUTH_API_KEY_QUERY, 'API key in query string'),
        (AUTH_API_KEY_HEADER, 'API key in header'),
        (AUTH_BEARER, 'Bearer token'),
    ]
    auth_type = models.CharField(max_length=20, choices=AUTH_CHOICES, default=AUTH_API_KEY_QUERY)
    auth_param_name = models.CharField(max_length=60, default='apiKey')
    single_endpoint_path = models.CharField(max_length=200, default='/leads')
    batch_endpoint_path = models.CharField(max_length=200, blank=True, default='/leads/batch')
    fetch_endpoint_path = models.CharField(max_length=200, blank=True, default='/leads')
    deposits_endpoint_path = models.CharField(max_length=200, blank=True, default='')
    batch_max_size = models.PositiveIntegerField(default=1, help_text='1 disables batching.')
    rate_limit_burst = models.PositiveIntegerField(default=10)
    rate_limit_refill_tokens = models.PositiveIntegerField(default=1)
    rate_limit_refill_seconds = models.PositiveIntegerField(default=1)
    # --- end legacy fields ---

    brand = models.ForeignKey(
        'brands.Brand', on_delete=models.CASCADE, related_name='lead_buyers',
        null=True, blank=True,
        help_text='Leave blank for a platform-wide buyer used when a brand has no dedicated one.',
    )
    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=60, unique=True)
    is_active = models.BooleanField(default=True)

    # Its own kill-switch — same shape as payouts' CRYPTO_DISPATCH_ENABLED /
    # NOWPAYMENTS_ALLOW_MAINNET. A buyer can be configured and proven out via
    # the management command / manual retry before ever receiving a lead
    # automatically on creation.
    auto_inject = models.BooleanField(default=False)

    base_url = models.URLField(max_length=500)
    api_key_encrypted = models.CharField(max_length=512, blank=True, default='')

    # Our field name -> the buyer's field name — OVERRIDES on top of
    # box_type.default_field_mapping (see get_effective_field_mapping). A
    # brand with zero quirks vs. the platform's canonical field set can
    # leave this empty entirely.
    field_mapping = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('name',)

    def __str__(self):
        return self.name

    def set_api_key(self, raw):
        self.api_key_encrypted = encrypt_secret(raw)

    def get_api_key(self):
        return decrypt_secret(self.api_key_encrypted)

    def get_effective_field_mapping(self):
        """box_type.default_field_mapping merged with this instance's own
        field_mapping — instance overrides win. The connector uses this
        (never the raw field_mapping) to map a Lead onto the buyer's field
        names, so a brand's quirks layer cleanly on top of the platform
        template without needing to repeat the whole mapping."""
        if not self.box_type_id:
            return dict(self.field_mapping)
        return {**self.box_type.default_field_mapping, **self.field_mapping}

    @property
    def supports_batch(self):
        if not self.box_type_id:
            return False
        return self.box_type.batch_max_size > 1 and bool(self.box_type.batch_endpoint_path)


class Lead(models.Model):
    """One captured consumer lead, regardless of intake channel."""

    CHANNEL_AFFILIATE_API = 'affiliate_api'
    CHANNEL_LANDING_PAGE = 'landing_page'
    CHANNEL_CHOICES = [
        (CHANNEL_AFFILIATE_API, 'Affiliate API'),
        (CHANNEL_LANDING_PAGE, 'Landing page'),
    ]

    STATUS_NEW = 'new'
    STATUS_INJECTED = 'injected'
    STATUS_DUPLICATE = 'duplicate'
    STATUS_REJECTED = 'rejected'
    STATUS_FAILED = 'failed'
    STATUS_DEPOSIT = 'deposit'
    # The whole resolved buyer chain (leadgen.routing.resolve_buyer_chain)
    # was tried — every buyer either had no match, terminally rejected, or
    # exhausted its transient retries — and nobody accepted it. Set by
    # leadgen.failover.advance_chain; see leadgen/README.md's Phase 2
    # section (build guide: Nexora_Lead_Distribution_Build_Guide.md).
    STATUS_UNROUTED = 'unrouted'
    STATUS_CHOICES = [
        (STATUS_NEW, 'New'),
        (STATUS_INJECTED, 'Injected'),
        (STATUS_DUPLICATE, 'Duplicate'),
        (STATUS_REJECTED, 'Rejected'),
        (STATUS_FAILED, 'Failed'),
        (STATUS_DEPOSIT, 'Deposit'),
        (STATUS_UNROUTED, 'Unrouted (chain exhausted)'),
    ]

    brand = models.ForeignKey(
        'brands.Brand', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='captured_leads',
    )
    intake_channel = models.CharField(max_length=20, choices=CHANNEL_CHOICES)

    # Set only for CHANNEL_AFFILIATE_API leads; null for direct landing-page
    # traffic — there's no Nexora affiliate in that path, the ad platform
    # itself (FB/Google) drove the click.
    affiliate = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='submitted_leads',
    )
    offer = models.ForeignKey(
        'offer.Offer', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='captured_leads',
    )
    click = models.ForeignKey(
        'tracker.Click', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='leads',
    )

    first_name = models.CharField(max_length=120, blank=True, default='')
    last_name = models.CharField(max_length=120, blank=True, default='')
    email = models.EmailField(max_length=250)
    phone = models.CharField(max_length=32)
    # Not set at intake — filled in best-effort, shortly after, by
    # tasks.geolocate_lead (IPSTACK lookup on `ip`, requires
    # settings.IPSTACK_TOKEN) and/or backfilled from a buyer's own
    # countryIso2 on the next tasks.sync_buyer_statuses run, whichever
    # lands first. Both paths only ever set this if it's still blank.
    country_iso2 = models.CharField(max_length=2, blank=True, default='')
    vertical = models.CharField(
        max_length=120, blank=True, default='',
        help_text="Campaign/vertical tag (the buyer's own 'affiliate' field, "
                  "e.g. 'crypto') — not a Nexora affiliate.",
    )
    source_id = models.CharField(max_length=120, blank=True, default='')

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_NEW)
    deposit = models.BooleanField(default=False)

    # The buyer's OWN free-text status for this lead once it's in their
    # system — "New", "Deposit", "Did not pick call", "Asked for followup",
    # whatever their call-center/CRM progression looks like. Not an enum:
    # every buyer defines their own set of values, so this is deliberately
    # a plain string kept in sync by leadgen.tasks.sync_buyer_statuses.
    # Denormalized from the delivered LeadInjection for cheap list display;
    # LeadInjection.buyer_status is the source of truth.
    buyer_status = models.CharField(max_length=120, blank=True, default='')
    buyer_status_updated_at = models.DateTimeField(null=True, blank=True)

    ip = models.GenericIPAddressField(null=True, blank=True)
    raw_payload = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('-created_at',)
        indexes = [
            models.Index(fields=['phone']),
            models.Index(fields=['email']),
            models.Index(fields=['status']),
        ]

    def __str__(self):
        return f'{self.full_name} <{self.email}>'.strip()

    @property
    def full_name(self):
        return f'{self.first_name} {self.last_name}'.strip()


class LeadInjection(models.Model):
    """One outbound delivery attempt — audited the same way as every other
    money/data-adjacent decision in this codebase (PayoutDecision,
    ImpersonationLog): every attempt is logged, nothing silent.

    Retry shape mirrors public_api.models.WebhookDelivery — same backoff
    philosophy for outbound delivery to a third party.
    """
    RETRY_BACKOFFS = [60, 300, 1800]  # seconds: 1 min, 5 min, 30 min

    STATUS_PENDING = 'pending'
    STATUS_DELIVERED = 'delivered'
    STATUS_DUPLICATE = 'duplicate'
    STATUS_FAILED = 'failed'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_DELIVERED, 'Delivered'),
        (STATUS_DUPLICATE, 'Duplicate (buyer already has this lead)'),
        (STATUS_FAILED, 'Failed'),
    ]

    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name='injections')
    buyer = models.ForeignKey(LeadBuyer, on_delete=models.CASCADE, related_name='injections')

    # True only for injections created by leadgen.failover.advance_chain —
    # the signal tasks.inject_lead_task uses to decide whether a terminal
    # outcome on THIS injection should advance the lead to the next buyer
    # in its resolved chain. False (the default) for every deliberate
    # single-buyer injection — the Django admin action, affiliate My Leads,
    # the operator dashboard, auto-inject on capture, the management
    # command — none of those should ever silently redirect to a different
    # buyer than the one a human (or auto_inject) explicitly chose.
    chain_managed = models.BooleanField(default=False)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    external_id = models.CharField(max_length=120, blank=True, default='')
    failure_reason = models.CharField(max_length=255, blank=True, default='')

    # The buyer's own status string for this specific delivery, as of the
    # last successful sync_buyer_statuses run — see Lead.buyer_status.
    buyer_status = models.CharField(max_length=120, blank=True, default='')
    buyer_status_updated_at = models.DateTimeField(null=True, blank=True)

    # Sanitized — never the API key (see connectors._sanitize_request_log).
    request_payload = models.JSONField(default=dict, blank=True)
    response_payload = models.JSONField(default=dict, blank=True)

    attempts = models.PositiveIntegerField(default=0)
    next_retry_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    delivered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ('-created_at',)

    def __str__(self):
        return f'{self.lead_id} -> {self.buyer.name} [{self.status}]'


class RoutingRule(models.Model):
    """A brand-scoped rule: leads matching every criterion set here (a blank/
    null criterion is a wildcard — matches anything) should be attempted
    against `buyer`, in `priority` order relative to other matching rules.

    Ordered by priority ascending — see leadgen.routing.resolve_buyer_chain,
    the pure function that turns a lead + the active rules for its brand
    into the ordered chain of buyers to attempt.

    `is_active` defaults to False, same kill-switch posture as
    LeadBuyer.auto_inject: a new rule is fully computed the moment you save
    it (visible via resolve_buyer_chain), but never actually influences
    delivery until you flip it on. As of Phase 1 (see leadgen/README.md),
    nothing calls resolve_buyer_chain from the delivery path yet either —
    routing is computed, not wired to auto-send."""

    brand = models.ForeignKey(
        'brands.Brand', on_delete=models.CASCADE, related_name='routing_rules',
        help_text='Every rule belongs to exactly one brand — no platform-wide routing rule.',
    )
    name = models.CharField(
        max_length=120, blank=True, default='',
        help_text='Optional human label, e.g. "US crypto leads -> BuyerX". Purely for your own scanning.',
    )

    # --- match criteria: blank/null = wildcard, matches any lead ---
    offer = models.ForeignKey(
        'offer.Offer', on_delete=models.SET_NULL, null=True, blank=True, related_name='routing_rules',
    )
    country_iso2 = models.CharField(max_length=2, blank=True, default='')
    affiliate = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='routing_rules',
    )
    vertical = models.CharField(max_length=120, blank=True, default='')
    source_channel = models.CharField(
        max_length=20, blank=True, default='',
        choices=[
            (Lead.CHANNEL_AFFILIATE_API, 'Affiliate API'),
            (Lead.CHANNEL_LANDING_PAGE, 'Landing page'),
            ('bought', 'Bought traffic'),  # no live intake channel sets this yet — see build guide Phase 6
        ],
    )

    buyer = models.ForeignKey(LeadBuyer, on_delete=models.CASCADE, related_name='routing_rules')
    priority = models.IntegerField(
        default=100, help_text='Lower is tried first among a lead\'s matching rules.',
    )
    is_active = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('priority', 'id')

    def __str__(self):
        return self.name or f'Rule #{self.pk} -> {self.buyer.name}'
