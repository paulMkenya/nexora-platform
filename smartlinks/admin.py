from django.contrib import admin

from .models import RoutingRule, SmartLink, SmartLinkClick


class RoutingRuleInline(admin.TabularInline):
    model = RoutingRule
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
