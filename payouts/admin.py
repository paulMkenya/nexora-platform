"""Model-admin registration for the withdrawal control layer.

The operator UI (`/admin/payouts/controls/`, `/admin/payouts/holds/`) is the
primary owner-facing surface; these registrations give the platform owner a
backup editing/inspection path in the stock Django admin.
"""
from django.contrib import admin

from payouts.models import (
    BrandWithdrawalControl, PayoutDecision, WithdrawalControlConfig,
)


@admin.register(WithdrawalControlConfig)
class WithdrawalControlConfigAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'enabled', 'approval_threshold', 'updated_at')

    def has_add_permission(self, request):
        # Singleton — only ever pk=1.
        return not WithdrawalControlConfig.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(BrandWithdrawalControl)
class BrandWithdrawalControlAdmin(admin.ModelAdmin):
    list_display = ('brand', 'per_tx_max', 'approval_threshold', 'updated_at')


@admin.register(PayoutDecision)
class PayoutDecisionAdmin(admin.ModelAdmin):
    list_display = ('id', 'payout_request', 'decision', 'amount', 'brand', 'actor', 'created_at')
    list_filter = ('decision',)
    readonly_fields = ('payout_request', 'decision', 'reason', 'amount', 'brand', 'actor', 'created_at')

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
