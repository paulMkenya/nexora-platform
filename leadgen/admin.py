from django import forms
from django.contrib import admin

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


@admin.register(Lead)
class LeadAdmin(admin.ModelAdmin):
    list_display = ('id', 'full_name', 'email', 'phone', 'status', 'intake_channel',
                     'brand', 'offer', 'affiliate', 'deposit', 'created_at')
    list_filter = ('status', 'intake_channel', 'brand', 'deposit')
    search_fields = ('first_name', 'last_name', 'email', 'phone', 'source_id')
    readonly_fields = [f.name for f in Lead._meta.fields]  # system-generated; not hand-edited
    date_hierarchy = 'created_at'

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
