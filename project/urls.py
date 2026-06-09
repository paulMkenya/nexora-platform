"""project URL Configuration"""
from django.conf import settings
from django.contrib import admin
from django.urls import path, include
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
)
from project.views import healthz
from affiliate_ui.views.general_views import AffiliateLoginView
from platform_leads.views import get_started
from brands.views.admin_views import dashboard as admin_dashboard

# Rebrand the Django model-admin chrome so it never reads "Django administration"
# (even on the platform owner host).
admin.site.site_header = settings.ADMIN_SITE_HEADER
admin.site.site_title = settings.ADMIN_SITE_HEADER
admin.site.index_title = settings.ADMIN_SITE_HEADER


urlpatterns = [
    path('', include('website.urls', namespace='website')),
    path('get-started/', get_started, name='get_started'),
    path('healthz', healthz, name='healthz'),
    path('account/', include('user_profile.urls', namespace='user_profile')),

    # Standalone /login/ kept for backward-compat (middleware tests, direct links)
    path('login/', AffiliateLoginView.as_view(), name='login'),

    path('admin/dashboard/', admin_dashboard, name='admin_dashboard'),
    path('admin/offers/', include('brands.offer_urls', namespace='offers_admin')),
    path('admin/advertisers/', include('brands.advertiser_urls', namespace='advertisers_admin')),
    path('admin/roles/', include('brands.role_urls', namespace='roles_admin')),
    path('admin/brands/', include('brands.urls', namespace='brands_admin')),
    path('admin/affiliates/', include('affiliate_ui.admin_urls', namespace='affiliate_admin')),
    path('admin/leads/', include('leads.urls', namespace='leads_admin')),
    path('admin/platform-leads/', include('platform_leads.urls', namespace='platform_leads_admin')),
    path('admin/archived/', include('brands.archived_urls', namespace='archived_admin')),
    path('admin/impersonate/', include('impersonation.urls', namespace='impersonation')),
    path('admin/fraud/', include('fraud.urls', namespace='fraud')),
    path('admin/payouts/', include('payouts.urls', namespace='payouts_admin')),
    path('mmp/', include('mmp.urls', namespace='mmp')),
    path('', include('billing.urls', namespace='billing')),
    path('webhooks/', include('payouts.webhook_urls')),
    path('admin/', admin.site.urls),

    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/schema/swagger-ui/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    # legacy alias kept for backward compatibility
    path('api/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui-legacy'),

    path('api/token/', TokenObtainPairView.as_view(),
        name='token_obtain_pair'),
    path('api/token/refresh/', TokenRefreshView.as_view(),
        name='token_refresh'),

    path('advertiser/', include('advertiser_ui.urls', namespace='advertiser_ui')),
    path('partner/', include('affiliate_ui.urls', namespace='affiliate_ui')),
    path('', include('smartlinks.urls')),
    path('affiliate/', include('affiliate.urls')),
    path('network/', include('network.urls')),
    path('', include('tracker.urls')),
    path('api/', include('dictionaries.urls')),
    path('tinymce/', include('tinymce.urls')),
    path('api/', include('api.urls')),
    path('api/v1/', include('reporting.urls')),
    path('api/v1/', include('public_api.urls')),
]
