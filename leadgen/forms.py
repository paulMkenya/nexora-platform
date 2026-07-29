"""Django forms for the Distribution console (leadgen/admin_views.py) —
the shared-shell equivalent of leadgen/admin.py's LeadBuyerAdminForm /
RoutingRuleAdmin, for operators who work the console rather than raw
Django admin (which stays available as the power-user fallback — see
leadgen/README.md's Phase 3 note)."""
from django import forms

from .models import LeadBuyer, RoutingRule


class LeadBuyerForm(forms.ModelForm):
    """Mirrors leadgen.admin.LeadBuyerAdminForm's write-only API key field
    exactly. Unlike the Django admin form, this one EXCLUDES the legacy
    pre-Box-Registry fields (auth_type, endpoint paths, rate limits — see
    models.py's "Legacy fields" comment) rather than showing them readonly:
    the console is meant to be the clean, primary surface (build guide
    3.3), and a field that does nothing when edited has no business being
    in a form an operator is expected to fill out. `field_mapping` here is
    this instance's OVERRIDES on top of box_type.default_field_mapping —
    see LeadBuyer.get_effective_field_mapping()."""
    api_key = forms.CharField(
        required=False, widget=forms.PasswordInput(render_value=False),
        help_text='Leave blank to keep the currently stored key unchanged.',
    )

    class Meta:
        model = LeadBuyer
        exclude = ['api_key_encrypted'] + list(LeadBuyer._LEGACY_FIELDS)
        widgets = {
            'field_mapping': forms.Textarea(attrs={
                'rows': 6,
                'placeholder': 'Overrides on top of the box type\'s defaults, e.g. '
                                '{"phone": "MobileNumber"} — leave {} if none.',
            }),
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
