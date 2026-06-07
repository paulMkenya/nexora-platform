"""URL conf for payouts app — admin-side."""
from django.urls import path
from .views import admin_views

app_name = 'payouts_admin'

urlpatterns = [
    path('', admin_views.payout_list, name='payout_list'),
    path('approve/', admin_views.bulk_approve, name='bulk_approve'),
    path('mark-paid/', admin_views.mark_paid, name='mark_paid'),
    path('dispatch/', admin_views.dispatch_approved, name='dispatch_approved'),
    path('csv/', admin_views.download_batch_csv, name='download_batch_csv'),
    path('batches/', admin_views.batch_list, name='batch_list'),
    # Withdrawal control layer
    path('holds/', admin_views.holds_list, name='holds_list'),
    path('holds/<int:pk>/approve/', admin_views.approve_hold, name='approve_hold'),
    path('holds/<int:pk>/deny/', admin_views.deny_hold, name='deny_hold'),
    path('controls/', admin_views.control_settings, name='control_settings'),
]
