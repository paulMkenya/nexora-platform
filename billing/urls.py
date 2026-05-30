from django.urls import path
from . import webhooks

app_name = 'billing'

urlpatterns = [
    path('webhooks/stripe/', webhooks.stripe_webhook, name='stripe_webhook'),
    path('webhooks/paystack/', webhooks.paystack_webhook, name='paystack_webhook'),
]
