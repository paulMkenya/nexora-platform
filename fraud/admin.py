from django.contrib import admin
from .models import FraudWhitelist


@admin.register(FraudWhitelist)
class FraudWhitelistAdmin(admin.ModelAdmin):
    list_display = ('entry_type', 'value', 'note', 'created_by', 'created_at')
    list_filter = ('entry_type',)
    search_fields = ('value', 'note')
    readonly_fields = ('created_at',)
