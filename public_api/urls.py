from django.urls import path

from .views.advertiser import (
    AdvertiserConversionBulkApproveView,
    AdvertiserConversionBulkRejectView,
    AdvertiserConversionListView,
    AdvertiserOfferDetailView,
    AdvertiserOfferListView,
    AdvertiserWalletView,
)
from .views.auth import APIKeyDetailView, APIKeyListCreateView, TokenView
from .views.network import (
    AdminAdvertiserListView,
    AdminConversionListView,
    AdminOfferDetailView,
    AdminOfferListView,
)
from .views.webhooks import (
    WebhookDeliveryListView,
    WebhookEndpointDetailView,
    WebhookEndpointListView,
)

urlpatterns = [
    # Auth
    path('auth/token', TokenView.as_view(), name='v1-token'),
    path('auth/keys', APIKeyListCreateView.as_view(), name='v1-keys'),
    path('auth/keys/<int:pk>', APIKeyDetailView.as_view(), name='v1-key-detail'),

    # Advertiser
    path('advertiser/offers', AdvertiserOfferListView.as_view(), name='v1-adv-offer-list'),
    path('advertiser/offers/<int:pk>', AdvertiserOfferDetailView.as_view(), name='v1-adv-offer-detail'),
    path('advertiser/conversions', AdvertiserConversionListView.as_view(), name='v1-adv-conv-list'),
    path('advertiser/conversions/bulk_approve',
         AdvertiserConversionBulkApproveView.as_view(), name='v1-adv-conv-approve'),
    path('advertiser/conversions/bulk_reject',
         AdvertiserConversionBulkRejectView.as_view(), name='v1-adv-conv-reject'),
    path('advertiser/wallet', AdvertiserWalletView.as_view(), name='v1-adv-wallet'),

    # Network admin
    path('admin/offers', AdminOfferListView.as_view(), name='v1-admin-offer-list'),
    path('admin/offers/<int:pk>', AdminOfferDetailView.as_view(), name='v1-admin-offer-detail'),
    path('admin/advertisers', AdminAdvertiserListView.as_view(), name='v1-admin-adv-list'),
    path('admin/conversions', AdminConversionListView.as_view(), name='v1-admin-conv-list'),

    # Webhooks
    path('admin/webhooks', WebhookEndpointListView.as_view(), name='v1-webhook-list'),
    path('admin/webhooks/<int:pk>', WebhookEndpointDetailView.as_view(), name='v1-webhook-detail'),
    path('admin/webhooks/<int:pk>/deliveries', WebhookDeliveryListView.as_view(), name='v1-webhook-deliveries'),
]
