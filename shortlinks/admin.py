from django.contrib import admin

from .models import ShortLink


@admin.register(ShortLink)
class ShortLinkAdmin(admin.ModelAdmin):
    list_display = ('slug', 'affiliate', 'offer', 'clicks', 'is_active', 'last_click_at', 'created_at')
    list_filter = ('is_active',)
    search_fields = ('slug', 'label', 'affiliate__username')
    list_select_related = ('affiliate', 'offer')
    raw_id_fields = ('affiliate', 'offer')
