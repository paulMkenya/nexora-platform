"""Django forms for the Distribution console (leadgen/admin_views.py) —
the shared-shell equivalent of leadgen/admin.py's LeadBuyerAdminForm /
RoutingRuleAdmin, for operators who work the console rather than raw
Django admin (which stays available as the power-user fallback — see
leadgen/README.md's Phase 3 note)."""
from django import forms

from .models import LeadBuyer, RoutingRule


class LeadBuyerForm(forms.ModelForm):
    """Mirrors leadgen.admin.LeadBuyerAdminForm exactly: the API key is
    write-only (encrypted at rest, see LeadBuyer.set_api_key) and never
    rendered back."""
    api_key = forms.CharField(
        required=False, widget=forms.PasswordInput(render_value=False),
        help_text='Leave blank to keep the currently stored key unchanged.',
    )

    class Meta:
        model = LeadBuyer
        exclude = ['api_key_encrypted']
        widgets = {
            'field_mapping': forms.Textarea(attrs={'rows': 6}),
        }

    def __init__(self, *args, restrict_to_brand=None, **kwargs):
        """restrict_to_brand: for a non-platform-owner operator, locks
        `brand` to their own brand (no platform-wide/other-brand option) —
        a brand-scoped operator must not be able to create or repoint a
        platform-wide buyer, which would affect every brand's fallback
        routing."""
        super().__init__(*args, **kwargs)
        if restrict_to_brand is not None:
            self.fields['brand'].queryset = self.fields['brand'].queryset.filter(pk=restrict_to_brand.pk)
            self.fields['brand'].initial = restrict_to_brand.pk
            self.fields['brand'].empty_label = None
            self.fields['brand'].required = True

    def save(self, commit=True):
        instance = super().save(commit=False)
        raw = self.cleaned_data.get('api_key')
        if raw:
            instance.set_api_key(raw)
        if commit:
            instance.save()
        return instance


class RoutingRuleForm(forms.ModelForm):
    class Meta:
        model = RoutingRule
        fields = [
            'brand', 'name', 'buyer', 'priority', 'is_active',
            'offer', 'country_iso2', 'affiliate', 'vertical', 'source_channel',
        ]

    def __init__(self, *args, restrict_to_brand=None, **kwargs):
        """restrict_to_brand: for a non-platform-owner operator, locks
        `brand` to their own brand — a rule always belongs to exactly one
        brand (RoutingRule.brand is required, unlike LeadBuyer's optional
        platform-wide option), so this just narrows the single choice
        rather than hiding an empty option."""
        super().__init__(*args, **kwargs)
        if restrict_to_brand is not None:
            self.fields['brand'].queryset = self.fields['brand'].queryset.filter(pk=restrict_to_brand.pk)
            self.fields['brand'].initial = restrict_to_brand.pk
