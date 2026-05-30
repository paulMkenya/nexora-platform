from django.contrib import admin
from .models import AdvertiserWallet, WalletTopUp, WalletTransaction, Invoice


class WalletTransactionInline(admin.TabularInline):
    model = WalletTransaction
    extra = 0
    readonly_fields = ('created_at', 'type', 'amount', 'balance_after', 'description', 'reference')
    can_delete = False


class WalletTopUpInline(admin.TabularInline):
    model = WalletTopUp
    extra = 0
    readonly_fields = ('created_at', 'provider', 'amount', 'status', 'external_ref')
    can_delete = False


@admin.register(AdvertiserWallet)
class AdvertiserWalletAdmin(admin.ModelAdmin):
    list_display = ('advertiser', 'balance', 'currency', 'credit_limit', 'low_balance_threshold',
                    'low_balance_alert_sent')
    list_filter = ('currency',)
    search_fields = ('advertiser__company',)
    inlines = [WalletTopUpInline, WalletTransactionInline]
    readonly_fields = ('created_at', 'updated_at')


@admin.register(WalletTopUp)
class WalletTopUpAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'wallet', 'provider', 'amount', 'status', 'external_ref')
    list_filter = ('provider', 'status')
    search_fields = ('external_ref',)
    readonly_fields = ('created_at',)


@admin.register(WalletTransaction)
class WalletTransactionAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'wallet', 'type', 'amount', 'balance_after', 'reference')
    list_filter = ('type',)
    search_fields = ('reference', 'description')
    readonly_fields = ('created_at',)


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ('period_start', 'wallet', 'subtotal', 'vat_amount', 'total', 'status')
    list_filter = ('status',)
    readonly_fields = ('created_at', 'pdf_url')
