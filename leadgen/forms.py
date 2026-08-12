"""Django forms for the Distribution console (leadgen/admin_views.py) —
the shared-shell equivalent of leadgen/admin.py's LeadBuyerAdminForm /
RoutingRuleAdmin, for operators who work the console rather than raw
Django admin (which stays available as the power-user fallback — see
leadgen/README.md's Phase 3 note)."""
import json

from django import forms

from .models import LeadBuyer, RoutingRule


class BuyerSecretsFormMixin(forms.Form):
    """Write-only handling for a LeadBuyer's two encrypted secret fields.

    INHERITS forms.Form, and must. Django collects a form's fields by
    walking the MRO for classes carrying a ``declared_fields`` attribute,
    which only its form metaclass produces. A PLAIN mixin's ``api_key =
    forms.CharField(...)`` is therefore never collected — it stays an inert
    class attribute, the field vanishes from the form, and
    ``cleaned_data.get('api_key')`` returns None. The failure is completely
    silent: the form still validates and still saves, it just quietly stops
    persisting the credential. That is exactly what happened when this mixin
    was first written as a plain class, and test_console's
    test_create_buyer_via_console caught it only because it asserts the
    round-tripped key rather than the redirect. Both behaviours are pinned
    in test_trackbox_connector.py::TestBuyerSecretsForms.

    Subclasses combine this with forms.ModelForm. The metaclass resolves to
    ModelFormMetaclass (the more derived of the two) and BaseModelForm still
    wins __init__ through the MRO, so ModelForm behaviour is unchanged.

    Both buyer forms — this module's console form and
    leadgen.admin.LeadBuyerAdminForm — need identical behaviour here, and
    the API-key half was already copy-pasted between them. A new secret
    field made that duplication actively dangerous rather than merely
    untidy: a ``*_encrypted`` column that any form forgets to exclude is
    rendered as its raw Fernet ciphertext in a plain text input, and saving
    that form writes the ciphertext back as though an operator had typed
    it. So the exclusion and the write-only replacements live in exactly one
    place and both forms mix this in.

    Subclasses MUST fold EXCLUDE into their own ``Meta.exclude`` — a
    ModelForm's Meta is not inherited through a plain mixin, so this class
    cannot do it for them.
    """

    EXCLUDE = ['api_key_encrypted', 'extra_credentials_encrypted']

    api_key = forms.CharField(
        required=False, widget=forms.PasswordInput(render_value=False),
        help_text='Leave blank to keep the currently stored key unchanged.',
    )
    extra_credentials = forms.CharField(
        required=False, widget=forms.Textarea(attrs={
            'rows': 3,
            'placeholder': '{"username": "...", "password": "..."}',
        }),
        help_text=(
            'JSON. Only for a box whose auth needs more than one secret — TrackBox '
            'wants a username and password alongside its API key. Leave blank to keep '
            'the stored values unchanged; never rendered back once saved.'
        ),
    )

    def clean_extra_credentials(self):
        """Reject anything that is not a JSON object, at the form rather
        than at injection time.

        Without this a typo is stored, encrypted, and only surfaces when a
        real lead fails to deliver with an auth error — long after the
        operator who made it has moved on.
        """
        raw = (self.cleaned_data.get('extra_credentials') or '').strip()
        if not raw:
            return ''
        try:
            parsed = json.loads(raw)
        except ValueError as exc:
            raise forms.ValidationError(f'Not valid JSON: {exc}') from exc
        if not isinstance(parsed, dict):
            raise forms.ValidationError('Must be a JSON object, e.g. {"username": "..."}.')
        if not all(isinstance(key, str) for key in parsed):
            raise forms.ValidationError('Every key must be a string.')
        return raw

    def save(self, commit=True):
        instance = super().save(commit=False)
        raw_key = self.cleaned_data.get('api_key')
        if raw_key:
            instance.set_api_key(raw_key)
        raw_extra = self.cleaned_data.get('extra_credentials')
        if raw_extra:
            instance.set_extra_credentials(json.loads(raw_extra))
        if commit:
            instance.save()
        return instance


class LeadBuyerForm(BuyerSecretsFormMixin, forms.ModelForm):
    """Write-only secret handling comes from BuyerSecretsFormMixin, shared
    with leadgen.admin.LeadBuyerAdminForm. Unlike that form, this one EXCLUDES the legacy
    pre-Box-Registry fields (auth_type, endpoint paths, rate limits — see
    models.py's "Legacy fields" comment) rather than showing them readonly:
    the console is meant to be the clean, primary surface (build guide
    3.3), and a field that does nothing when edited has no business being
    in a form an operator is expected to fill out. `field_mapping` here is
    this instance's OVERRIDES on top of box_type.default_field_mapping —
    see LeadBuyer.get_effective_field_mapping()."""

    class Meta:
        model = LeadBuyer
        exclude = BuyerSecretsFormMixin.EXCLUDE + list(LeadBuyer._LEGACY_FIELDS)
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
