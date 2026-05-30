from django.contrib import admin
from .models import MMP, MMPCallback


@admin.register(MMP)
class MMPAdmin(admin.ModelAdmin):
    list_display = ('name', 'vendor')
    readonly_fields = ('vendor',)


@admin.register(MMPCallback)
class MMPCallbackAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'vendor', 'click_id', 'event_name', 'processed')
    list_filter = ('vendor', 'processed')
    search_fields = ('click_id',)
    readonly_fields = ('created_at', 'vendor', 'click_id', 'event_name', 'raw_data')
