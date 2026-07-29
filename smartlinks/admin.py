from django import forms
from django.contrib import admin

from user_profile.geo import CountryListField

from .models import RoutingRule, SmartLink, SmartLinkClick


class RoutingRuleInlineForm(forms.ModelForm):
    """countries is stored as a comma-separated ISO-alpha-2 string (see
    RoutingRule.countries' help_text) — CountryListField renders it as a
    proper multi-select and converts to/from that CSV shape on save."""
    countries = CountryListField(help_text='Leave empty to match any country.')

    class Meta:
        model = RoutingRule
        fields = ('priority', 'destination_url', 'countries', 'device_type', 'is_active')


class RoutingRuleInline(admin.TabularInline):
    model = RoutingRule
    form = RoutingRuleInlineForm
    extra = 1
    fields = ('priority', 'destination_url', 'countries', 'device_type', 'is_active')


@admin.register(SmartLink)
class SmartLinkAdmin(admin.ModelAdmin):
    list_display = ('alias', 'name', 'is_active', 'created_at')
    list_filter = ('is_active',)
    search_fields = ('alias', 'name')
    inlines = [RoutingRuleInline]
    prepopulated_fields = {'alias': ('name',)}


@admin.register(SmartLinkClick)
class SmartLinkClickAdmin(admin.ModelAdmin):
    list_display = ('id', 'created_at', 'smart_link', 'affiliate', 'country', 'device_type', 'destination_url')
    list_filter = ('device_type', 'country')
    readonly_fields = ('id', 'created_at')
    raw_id_fields = ('smart_link', 'affiliate')
