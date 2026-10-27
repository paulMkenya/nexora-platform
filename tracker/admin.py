from django.contrib import admin
from .models import Click, Conversion


@admin.register(Click)
class ClickAdmin(admin.ModelAdmin):
    list_display = ('id', 'created_at', 'offer', 'affiliate', 'country', 'asn', 'isp', 'is_mobile', 'ip')
    list_filter = ('country', 'is_mobile')
    search_fields = ('ip', 'isp')
    list_select_related = ('offer', 'affiliate')


@admin.register(Conversion)
class ConversionAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'created_at',
        'affiliate',
        'offer',
        'revenue',
        'payout',
        'goal',
        'status',
        'ip',
        'country',
        'txid',
        'comment',
    )
