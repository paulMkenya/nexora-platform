from django import forms
from django.contrib import admin, messages
from django.contrib.admin import helpers
from django.template.response import TemplateResponse

from .models import Lead, LeadBuyer, LeadInjection


class LeadBuyerAdminForm(forms.ModelForm):
    """The API key is write-only (encrypted at rest, see LeadBuyer.set_api_key)
    — never rendered back, same UX as Brand's SMTP password field."""
    api_key = forms.CharField(
        required=False, widget=forms.PasswordInput(render_value=False),
        help_text='Leave blank to keep the currently stored key unchanged.',
    )

    class Meta:
        model = LeadBuyer
        exclude = ['api_key_encrypted']

    def save(self, commit=True):
        instance = super().save(commit=False)
        raw = self.cleaned_data.get('api_key')
        if raw:
            instance.set_api_key(raw)
        if commit:
            instance.save()
        return instance


@admin.register(LeadBuyer)
class LeadBuyerAdmin(admin.ModelAdmin):
    form = LeadBuyerAdminForm
    list_display = ('name', 'brand', 'is_active', 'auto_inject', 'base_url', 'batch_max_size', 'updated_at')
    list_filter = ('is_active', 'auto_inject', 'brand')
    search_fields = ('name', 'slug', 'base_url')
    readonly_fields = ('created_at', 'updated_at')


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

        from .tasks import inject_lead_task

        delivered = duplicate = failed = 0
        for lead in queryset:
            injection = LeadInjection.objects.create(lead=lead, buyer=buyer)
            try:
                inject_lead_task(injection.pk)
            except Exception:
                pass  # a scheduled Celery retry raises Retry — state is already saved
            injection.refresh_from_db()

            if injection.status == LeadInjection.STATUS_DELIVERED:
                delivered += 1
            elif injection.status == LeadInjection.STATUS_DUPLICATE:
                duplicate += 1
            else:
                failed += 1
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
    list_display = ('id', 'full_name', 'email', 'phone', 'status', 'intake_channel',
                     'brand', 'offer', 'affiliate', 'deposit', 'created_at')
    list_filter = ('status', 'intake_channel', 'brand', 'deposit')
    search_fields = ('first_name', 'last_name', 'email', 'phone', 'source_id')
    readonly_fields = [f.name for f in Lead._meta.fields]  # system-generated; not hand-edited
    date_hierarchy = 'created_at'
    actions = [inject_to_buyer]

    def has_add_permission(self, request):
        return False


@admin.register(LeadInjection)
class LeadInjectionAdmin(admin.ModelAdmin):
    list_display = ('id', 'lead', 'buyer', 'status', 'attempts', 'external_id', 'created_at', 'delivered_at')
    list_filter = ('status', 'buyer')
    search_fields = ('lead__email', 'lead__phone', 'external_id')
    readonly_fields = [f.name for f in LeadInjection._meta.fields]  # audit trail — never hand-edited
    date_hierarchy = 'created_at'

    def has_add_permission(self, request):
        return False
