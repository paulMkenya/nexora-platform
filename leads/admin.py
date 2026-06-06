from django.contrib import admin

from leads.models import Lead


@admin.register(Lead)
class LeadAdmin(admin.ModelAdmin):
    list_display = ('name', 'email', 'lead_type', 'brand', 'pipeline_stage',
                    'last_activity_at', 'created_at')
    list_filter = ('lead_type', 'pipeline_stage', 'brand')
    search_fields = ('name', 'email')
    readonly_fields = ('created_at',)
    autocomplete_fields = ()
    raw_id_fields = ('profile', 'advertiser')
