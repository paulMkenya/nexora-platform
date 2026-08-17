from django import forms
from django.contrib import admin, messages
from django.contrib.admin import helpers
from django.template.response import TemplateResponse

from .forms import BuyerSecretsFormMixin
from .models import (
    AffiliateOfferLink, AffiliatePostbackConfig, BoxType, Lead, LeadBuyer, LeadInjection,
    LeadStatusEvent, PostbackDelivery, RoutingRule,
)


@admin.register(BoxType)
class BoxTypeAdmin(admin.ModelAdmin):
    """Phase 4 of the lead-distribution build (see leadgen/README.md's Box
    Registry section): the reusable, platform-level template every
    same-platform LeadBuyer instance shares. Edit here to change something
    for EVERY buyer on this box at once (e.g. the platform changed an
    endpoint path) — per-brand specifics belong on the LeadBuyer row
    instead, never here."""
    list_display = ('name', 'version', 'slug', 'auth_type', 'batch_max_size', 'updated_at')
    search_fields = ('name', 'slug', 'description')
    readonly_fields = ('created_at', 'updated_at')


class LeadBuyerAdminForm(BuyerSecretsFormMixin, forms.ModelForm):
    """Both encrypted secrets are write-only (see LeadBuyer.set_api_key /
    set_extra_credentials) — never rendered back, same UX as Brand's SMTP
    password field. The behaviour lives in BuyerSecretsFormMixin, shared
    with the console's own LeadBuyerForm; only Meta differs between the
    two, because this form still shows the legacy fields readonly."""

    class Meta:
        model = LeadBuyer
        exclude = BuyerSecretsFormMixin.EXCLUDE


@admin.register(LeadBuyer)
class LeadBuyerAdmin(admin.ModelAdmin):
    form = LeadBuyerAdminForm
    list_display = ('name', 'box_type', 'brand', 'is_active', 'auto_inject', 'base_url', 'updated_at')
    list_filter = ('is_active', 'auto_inject', 'brand', 'box_type')
    search_fields = ('name', 'slug', 'base_url')
    readonly_fields = ('created_at', 'updated_at') + LeadBuyer._LEGACY_FIELDS


def inject_to_buyer(modeladmin, request, queryset):
    """Manual injection action: pick one or more leads, choose a buyer on an
    intermediate page, click Inject — runs synchronously (not queued via
    Celery .delay()) so the admin gets an immediate delivered/duplicate/failed
    result per lead, same connector + retry-state bookkeeping as the
    automatic path (tasks.inject_lead_task), just called inline."""
    if 'apply' in request.POST:
        buyer_id = request.POST.get('buyer_id')
        buyer = LeadBuyer.objects.filter(pk=buyer_id, is_active=True).first()
        if not buyer:
            modeladmin.message_user(request, 'Select a valid, active buyer.', level=messages.ERROR)
            return None

        from .services import inject_leads_to_buyer, summarize_injection_results

        results = inject_leads_to_buyer(list(queryset), buyer)
        delivered, duplicate, failed = summarize_injection_results(results)
        for lead, injection in results:
            if injection.status not in (LeadInjection.STATUS_DELIVERED, LeadInjection.STATUS_DUPLICATE):
                modeladmin.message_user(
                    request,
                    f'Lead #{lead.pk} ({lead.email}) → {buyer.name}: {injection.failure_reason or injection.status}',
                    level=messages.WARNING,
                )

        summary = f'Injected to {buyer.name}: {delivered} delivered, {duplicate} duplicate, {failed} failed.'
        modeladmin.message_user(request, summary, level=messages.SUCCESS if not failed else messages.WARNING)
        return None

    buyers = LeadBuyer.objects.filter(is_active=True).order_by('name')
    return TemplateResponse(request, 'leadgen/admin/inject_to_buyer.html', {
        'leads': queryset,
        'buyers': buyers,
        'action_checkbox_name': helpers.ACTION_CHECKBOX_NAME,
        'opts': modeladmin.model._meta,
        'title': 'Inject selected leads to buyer',
    })


inject_to_buyer.short_description = 'Inject selected leads to buyer…'


@admin.register(Lead)
class LeadAdmin(admin.ModelAdmin):
    list_display = ('id', 'full_name', 'email', 'phone', 'status', 'lead_deposit_status',
                     'canonical_status', 'canonical_status_needs_review',
                     'intake_channel', 'brand', 'offer', 'affiliate', 'deposit', 'created_at')
    list_filter = ('status', 'canonical_status', 'canonical_status_needs_review',
                    'intake_channel', 'brand', 'affiliate', 'deposit')
    search_fields = ('first_name', 'last_name', 'email', 'phone', 'source_id')
    readonly_fields = [f.name for f in Lead._meta.fields]  # system-generated; not hand-edited
    date_hierarchy = 'created_at'
    actions = [inject_to_buyer]

    def has_add_permission(self, request):
        return False

    def lead_deposit_status(self, obj):
        return obj.buyer_status or '—'
    lead_deposit_status.short_description = 'Lead Deposit Status'
    lead_deposit_status.admin_order_field = 'buyer_status'


@admin.register(LeadInjection)
class LeadInjectionAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'lead', 'buyer', 'status', 'chain_managed', 'buyer_status', 'attempts',
        'external_id', 'created_at', 'delivered_at')
    list_filter = ('status', 'buyer', 'chain_managed')
    search_fields = ('lead__email', 'lead__phone', 'external_id')
    readonly_fields = [f.name for f in LeadInjection._meta.fields]  # audit trail — never hand-edited
    date_hierarchy = 'created_at'

    def has_add_permission(self, request):
        return False


@admin.register(RoutingRule)
class RoutingRuleAdmin(admin.ModelAdmin):
    """The lead-distribution routing rules (see leadgen/routing.py):
    create/edit them here. is_active defaults to False on every new rule —
    saving one here computes it into resolve_buyer_chain() immediately, but
    it stays inert until you flip is_active on, same posture as
    LeadBuyer.auto_inject.

    Flipping is_active on DOES now change live delivery: the capture path
    picks its buyer from these rules (leadgen.tasks.resolve_buyer_for_lead).
    A brand's first active rule switches that brand off the legacy
    alphabetically-first-buyer pick for good, so seed its wildcard parity
    rule first — see that function's docstring."""
    list_display = ('__str__', 'brand', 'buyer', 'priority', 'is_active',
                     'offer', 'country_iso2', 'affiliate', 'vertical', 'source_channel', 'updated_at')
    list_filter = ('is_active', 'brand', 'buyer', 'source_channel')
    search_fields = ('name', 'country_iso2', 'vertical')
    autocomplete_fields = ('offer', 'affiliate')
    readonly_fields = ('created_at', 'updated_at')
    fieldsets = (
        (None, {'fields': ('brand', 'name', 'buyer', 'priority', 'is_active')}),
        ('Match criteria (blank = matches any lead)', {
            'fields': ('offer', 'country_iso2', 'affiliate', 'vertical', 'source_channel'),
        }),
        ('Timestamps', {'fields': ('created_at', 'updated_at')}),
    )


@admin.register(AffiliateOfferLink)
class AffiliateOfferLinkAdmin(admin.ModelAdmin):
    """Affiliate Inbound API spec Phase 1/2 — the two-phase status authority
    for one (affiliate, offer) pair. Rows are get_or_create'd automatically
    by leadgen.status_sync the first time a status change is attempted for a
    pair (see resolve_affiliate_offer_link) — never hand-created here.
    Read-only for the same reason phase/phase_changed_at/phase_changed_by
    must never be hand-edited: go_live()/revert_to_testing() are what stamp
    the audit fields correctly. The real "Go live" action (a button with
    confirmation, per spec §2.1) is the operator-UI phase of this build, not
    yet built — until then this view is for visibility/debugging only."""
    list_display = ('affiliate', 'offer', 'phase', 'phase_changed_at', 'phase_changed_by', 'updated_at')
    list_filter = ('phase',)
    search_fields = ('affiliate__username', 'affiliate__email', 'offer__title')
    readonly_fields = [f.name for f in AffiliateOfferLink._meta.fields]

    def has_add_permission(self, request):
        return False


@admin.register(LeadStatusEvent)
class LeadStatusEventAdmin(admin.ModelAdmin):
    """Append-only status timeline — spec §3.3. Never hand-edited; every row
    is written by leadgen.status_sync.apply_status_change."""
    list_display = ('id', 'lead', 'from_status', 'to_status', 'source', 'applied',
                     'phase_at_time', 'lead_seq', 'actor', 'created_at')
    list_filter = ('source', 'applied', 'phase_at_time', 'to_status')
    search_fields = ('lead__email', 'lead__phone')
    readonly_fields = [f.name for f in LeadStatusEvent._meta.fields]
    date_hierarchy = 'created_at'

    def has_add_permission(self, request):
        return False


@admin.register(AffiliatePostbackConfig)
class AffiliatePostbackConfigAdmin(admin.ModelAdmin):
    """Affiliate Inbound API spec Phase 4 (§5.1): one postback URL for an
    affiliate. The self-service affiliate-facing form is Phase 6 — this is
    the operator fallback for configuring one on an affiliate's behalf in
    the meantime (same posture LeadBuyerAdmin has always had relative to
    the Distribution console)."""
    list_display = ('url', 'affiliate', 'is_active', 'subscribed_statuses', 'updated_at')
    list_filter = ('is_active',)
    search_fields = ('url', 'affiliate__username', 'affiliate__email')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(PostbackDelivery)
class PostbackDeliveryAdmin(admin.ModelAdmin):
    """One postback delivery attempt — audit trail, never hand-edited.
    Spec §5.1: "Affiliate can see delivery status in their UI" — Phase 6's
    affiliate-facing view; this is the operator/debugging view for now."""
    list_display = ('id', 'config', 'status_event', 'status', 'attempts',
                     'response_status_code', 'created_at', 'delivered_at')
    list_filter = ('status',)
    search_fields = ('config__affiliate__email', 'url')
    readonly_fields = [f.name for f in PostbackDelivery._meta.fields]
    date_hierarchy = 'created_at'

    def has_add_permission(self, request):
        return False
