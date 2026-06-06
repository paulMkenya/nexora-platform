from django.contrib import admin

from platform_leads.models import PlatformLead


@admin.register(PlatformLead)
class PlatformLeadAdmin(admin.ModelAdmin):
    list_display = ('name', 'email', 'lead_type', 'sales_stage',
                    'company', 'country', 'created_at', 'last_contact_at')
    list_filter = ('lead_type', 'sales_stage', 'timeline')
    search_fields = ('name', 'email', 'company', 'phone')
    readonly_fields = ('created_at',)
    filter_horizontal = ('verticals', 'traffic_sources')
