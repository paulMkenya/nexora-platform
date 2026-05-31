from django import forms
from django.contrib.auth import get_user_model, password_validation
from django.core.exceptions import ValidationError

from user_profile.geo import country_choices

User = get_user_model()


class AffiliateRegistrationForm(forms.Form):
    first_name = forms.CharField(max_length=150, label='First name')
    last_name = forms.CharField(max_length=150, label='Last name')
    email = forms.EmailField(label='Email address')
    password1 = forms.CharField(widget=forms.PasswordInput, label='Password')
    password2 = forms.CharField(widget=forms.PasswordInput, label='Confirm password')
    traffic_source = forms.CharField(max_length=100, required=False, label='Traffic source (optional)')
    country = forms.ChoiceField(required=False, label='Country (optional)')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Single source of country data: countries_plus. Stored as ISO alpha-2.
        self.fields['country'].choices = country_choices()

    def clean_email(self):
        email = self.cleaned_data['email'].lower()
        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError('An account with this email already exists.')
        return email

    def clean_password1(self):
        password = self.cleaned_data.get('password1')
        if password:
            password_validation.validate_password(password)
        return password

    def clean(self):
        cleaned = super().clean()
        p1 = cleaned.get('password1')
        p2 = cleaned.get('password2')
        if p1 and p2 and p1 != p2:
            self.add_error('password2', 'Passwords do not match.')
        return cleaned
