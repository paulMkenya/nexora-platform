"""Webhook URL patterns (mounted at /webhooks/ in project/urls.py)."""
from django.urls import path
from . import webhooks

urlpatterns = [
    path('mpesa/b2c/', webhooks.mpesa_b2c_callback, name='mpesa_b2c_callback'),
    path('nowpayments/', webhooks.nowpayments_ipn, name='nowpayments_ipn'),
]
