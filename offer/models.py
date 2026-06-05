from django.conf import settings
from django.db import models
from countries_plus.models import Country
from tinymce import models as tinymce_models
from brands.archival import Archivable
from brands.managers import BrandScopedManager


ACTIVE_STATUS = 'Active'
PAUSED_STATUS = 'Paused'
STOPPED_STATUS = 'Stopped'
offer_statuses = (
    (ACTIVE_STATUS, 'Active'),
    (PAUSED_STATUS, 'Paused'),
    (STOPPED_STATUS, 'Stopped'),
)


# Revenue / payout models selectable per offer. These are the industry-standard
# affiliate pricing models; the value stored is the short code.
CPA = 'CPA'
CPL = 'CPL'
CPS = 'CPS'
CPI = 'CPI'
CPC = 'CPC'
REVSHARE = 'RevShare'
HYBRID = 'Hybrid'
revenue_models = (
    (CPA, 'CPA — Cost Per Action'),
    (CPL, 'CPL — Cost Per Lead'),
    (CPS, 'CPS — Cost Per Sale'),
    (CPI, 'CPI — Cost Per Install'),
    (CPC, 'CPC — Cost Per Click'),
    (REVSHARE, 'RevShare — Revenue Share'),
    (HYBRID, 'Hybrid — CPA + RevShare'),
)


# Country targeting modes (see Offer.accepts_country / targeting_display).
ALLOW_ALL = 'ALLOW_ALL'
ALLOW_LIST = 'ALLOW_LIST'
BLOCK_LIST = 'BLOCK_LIST'
country_modes = (
    (ALLOW_ALL, 'Global — accept all countries'),
    (ALLOW_LIST, 'Allow list — only listed countries'),
    (BLOCK_LIST, 'Block list — all except listed countries'),
)


class Offer(models.Model):

    class Meta:
        ordering = ('-id',)

    objects = BrandScopedManager()

    brand = models.ForeignKey(
        'brands.Brand',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='offers',
    )
    title = models.CharField(max_length=256, default='')
    description = models.TextField(blank=True, default='')
    description_html = tinymce_models.HTMLField(default='', blank=True)
    tracking_link = models.CharField(max_length=1024, default='')
    preview_link = models.CharField(max_length=1024, default='')
    countries = models.ManyToManyField(Country)
    categories = models.ManyToManyField('Category', blank=True)
    traffic_sources = models.ManyToManyField(
        'TrafficSource', through='OfferTrafficSource', blank=True)
    status = models.CharField(max_length=20, choices=offer_statuses,
                              default=ACTIVE_STATUS)
    revenue_model = models.CharField(
        max_length=16, choices=revenue_models, default=CPA,
        help_text='Pricing model affiliates are paid under for this offer.')
    country_mode = models.CharField(
        max_length=12, choices=country_modes, default=ALLOW_ALL,
        help_text='How the country list below is applied.')
    icon = models.CharField(max_length=255,
                            default=None, blank=True, null=True)
    advertiser = models.ForeignKey(
        'Advertiser',
        on_delete=models.SET_NULL,
        null=True, blank=True, default=None)

    mmp = models.ForeignKey(
        'mmp.MMP',
        on_delete=models.SET_NULL,
        null=True, blank=True, default=None,
        related_name='offers',
    )
    mmp_app_id = models.CharField(max_length=128, default='', blank=True)
    mmp_extra = models.JSONField(default=dict, blank=True)

    def __str__(self):
        return f"({self.id}) {self.title}"

    def accepts_country(self, code):
        """Return True if a click from ISO alpha-2 ``code`` is accepted.

        Used consistently wherever country eligibility is checked. ALLOW_ALL
        always accepts; ALLOW_LIST accepts only listed countries; BLOCK_LIST
        accepts everything except the listed countries.
        """
        if self.country_mode == ALLOW_ALL:
            return True
        listed = {c.upper() for c in self.countries.values_list('iso', flat=True)}
        code = (code or '').upper()
        if self.country_mode == ALLOW_LIST:
            return code in listed
        if self.country_mode == BLOCK_LIST:
            return code not in listed
        return True

    def targeting_display(self):
        """Human-readable summary of the effective country targeting.

        e.g. "Global", "KE, UG, TZ only", "Global except NG, GH".
        """
        if self.country_mode == ALLOW_ALL:
            return 'Global'
        codes = sorted(c.upper() for c in self.countries.values_list('iso', flat=True))
        if not codes:
            # No countries listed: an allow-list accepts nobody; a block-list
            # blocks nobody (i.e. effectively global).
            return 'No countries' if self.country_mode == ALLOW_LIST else 'Global'
        joined = ', '.join(codes)
        if self.country_mode == ALLOW_LIST:
            return f'{joined} only'
        return f'Global except {joined}'


class Category(models.Model):
    class Meta:
        ordering = ('name',)
        verbose_name_plural = 'Categories'

    name = models.CharField(max_length=256)
    # Adult / restricted vertical (e.g. Adult, some Dating). Lets the platform
    # owner flag verticals that need extra handling.
    is_adult = models.BooleanField(
        default=False,
        help_text='Adult / restricted vertical.')

    def __str__(self):
        return self.name


class TrafficSource(models.Model):
    name = models.CharField(max_length=256)

    def __str__(self):
        return self.name


class OfferTrafficSource(models.Model):
    offer = models.ForeignKey(Offer, on_delete=models.CASCADE)
    traffic_source = models.ForeignKey(TrafficSource, on_delete=models.CASCADE)
    allowed = models.BooleanField(default=True)


FIXED_PAYOUT = 'Fixed'
PERCENT_PAYOUT = 'Percent'
payout_types = (
    (FIXED_PAYOUT, 'Fixed'),
    (PERCENT_PAYOUT, 'Percent'),
)


class Goal(models.Model):
    name = models.CharField(max_length=64)

    def __str__(self):
        return self.name


class Currency(models.Model):
    class Meta:
        ordering = ('code',)
        verbose_name_plural = 'Currencies'

    code = models.CharField(max_length=3)
    name = models.CharField(max_length=128)
    symbol = models.CharField(max_length=8, default='', blank=True)

    def __str__(self):
        return f'{self.code} — {self.name}'


class Payout(models.Model):

    class Meta:
        ordering = ('-payout',)

    revenue = models.DecimalField(max_digits=7, decimal_places=2)
    payout = models.DecimalField(max_digits=7, decimal_places=2)
    countries = models.ManyToManyField(Country)
    goal_value = models.CharField(max_length=20, default='1')
    type = models.CharField(
        max_length=20,
        choices=payout_types,
        default=FIXED_PAYOUT
    )

    currency = models.ForeignKey(
        Currency,
        on_delete=models.CASCADE
    )

    goal = models.ForeignKey(
        Goal,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    offer = models.ForeignKey(
        Offer,
        related_name='payouts',
        on_delete=models.CASCADE
    )


class Advertiser(Archivable):
    objects = BrandScopedManager()

    class AdvertiserStatus(models.TextChoices):
        PENDING = 'PENDING', 'Pending'
        APPROVED = 'APPROVED', 'Approved'
        REJECTED = 'REJECTED', 'Rejected'
        SUSPENDED = 'SUSPENDED', 'Suspended'

    brand = models.ForeignKey(
        'brands.Brand',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='advertisers',
    )
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='advertiser_profile',
    )
    company = models.CharField(max_length=64)
    email = models.CharField(max_length=64)
    contact_person = models.CharField(max_length=64, default='')
    messenger = models.CharField(max_length=64, default='')
    site = models.CharField(max_length=64, default='')
    # ISO-3166-1 alpha-2 country code (sourced from countries_plus). Blank = unset.
    country = models.CharField(max_length=2, default='', blank=True)
    comment = models.TextField(default='', blank=True)
    # Self-registration / approval gating (mirrors the affiliate model on
    # user_profile.Profile). New self-registered advertisers start PENDING and
    # unverified; only APPROVED + email_verified advertisers may create offers
    # and have their offers shown to affiliates. Existing advertisers (created
    # before onboarding existed) are grandfathered to APPROVED + verified by the
    # data migration so the live offer flow is never interrupted.
    advertiser_status = models.CharField(
        max_length=10,
        choices=AdvertiserStatus.choices,
        default=AdvertiserStatus.PENDING,
    )
    email_verified = models.BooleanField(default=False)

    def __str__(self):
        return self.company

    @property
    def is_active_advertiser(self):
        """True once the advertiser is approved, email-verified and not archived."""
        return (
            self.advertiser_status == self.AdvertiserStatus.APPROVED
            and self.email_verified
            and not self.is_archived
        )


class Landing(models.Model):
    name = models.CharField(max_length=100)
    url = models.CharField(max_length=1024, default='')
    preview_url = models.CharField(max_length=1024, default='')

    offer = models.ForeignKey(
        Offer,
        related_name='landings',
        on_delete=models.CASCADE
    )

    def __str__(self):
        return f'{self.id}: {self.name}'


class AdvertiserPostbackKey(models.Model):
    """Per-advertiser HMAC-SHA256 secret for inbound S2S postback verification."""

    advertiser = models.OneToOneField(
        Advertiser,
        on_delete=models.CASCADE,
        related_name='postback_key',
    )
    secret = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'key:{self.advertiser}'
