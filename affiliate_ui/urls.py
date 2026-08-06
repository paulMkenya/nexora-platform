from django.urls import path
from django.views.generic import RedirectView
from .views.general_views import AffiliateLoginView, affiliate_logout, dashboard, offer_list, offer_detail
from .views.registration_views import register, verify_email
from .views.report_views import daily_report_view, offer_report_view, goal_report_view
from .views.leads_views import my_leads, inject_my_leads
from .views.api_docs_views import (
    api_docs, api_docs_pdf, api_docs_text, api_keys,
    api_key_create, api_key_regenerate, api_key_revoke,
)
from .views.postbacks_views import postbacks, postback_create, postback_update, postback_toggle_active
from .views.settings_views import company_settings, company_settings_update
from .views.auth_views import (
    BrandPasswordResetView,
    BrandPasswordResetDoneView,
    BrandPasswordResetConfirmView,
    BrandPasswordResetCompleteView,
)
from payouts.views.affiliate_views import (
    payouts_home, add_payout_method, delete_payout_method,
    set_default_method, request_early_payout, update_payout_settings,
    validate_address_api, fee_estimate_api,
)

app_name = 'affiliate_ui'

urlpatterns = [
    path('', RedirectView.as_view(url='dashboard/', permanent=False), name='home'),
    path('login/', AffiliateLoginView.as_view(), name='login'),
    path('logout/', affiliate_logout, name='logout'),
    path('register/', register, name='register'),
    path('verify-email/<str:token>/', verify_email, name='verify_email'),
    # Self-service password reset (brand-aware)
    path('password-reset/', BrandPasswordResetView.as_view(), name='password_reset'),
    path('password-reset/done/', BrandPasswordResetDoneView.as_view(), name='password_reset_done'),
    path('reset/<uidb64>/<token>/', BrandPasswordResetConfirmView.as_view(), name='password_reset_confirm'),
    path('reset/done/', BrandPasswordResetCompleteView.as_view(), name='password_reset_complete'),
    path('dashboard/', dashboard, name='dashboard'),
    path('settings/', company_settings, name='company_settings'),
    path('settings/save/', company_settings_update, name='company_settings_update'),
    path('offers/', offer_list, name='offer_list'),
    path('offers/<int:offer_id>/', offer_detail, name='offer_detail'),
    path('reports/daily/', daily_report_view, name='daily_report'),
    path('reports/offer/', offer_report_view, name='offer_report'),
    path('reports/goal/', goal_report_view, name='goal_report'),
    # Leads
    path('leads/', my_leads, name='my_leads'),
    path('leads/inject/', inject_my_leads, name='inject_my_leads'),
    # API & Docs (Affiliate Inbound API spec Phase 5)
    path('api-docs/', api_docs, name='api_docs'),
    path('api-docs/pdf/', api_docs_pdf, name='api_docs_pdf'),
    path('api-docs/text/', api_docs_text, name='api_docs_text'),
    path('api-docs/keys/', api_keys, name='api_keys'),
    path('api-docs/keys/create/', api_key_create, name='api_key_create'),
    path('api-docs/keys/<int:pk>/regenerate/', api_key_regenerate, name='api_key_regenerate'),
    path('api-docs/keys/<int:pk>/revoke/', api_key_revoke, name='api_key_revoke'),
    # Postbacks (Affiliate Inbound API spec Phase 6)
    path('postbacks/', postbacks, name='postbacks'),
    path('postbacks/create/', postback_create, name='postback_create'),
    path('postbacks/<int:pk>/update/', postback_update, name='postback_update'),
    path('postbacks/<int:pk>/toggle-active/', postback_toggle_active, name='postback_toggle_active'),
    # Payouts
    path('payouts/', payouts_home, name='payouts'),
    path('payouts/methods/add/', add_payout_method, name='add_payout_method'),
    path('payouts/methods/<int:pk>/delete/', delete_payout_method, name='delete_payout_method'),
    path('payouts/methods/<int:pk>/set-default/', set_default_method, name='set_default_method'),
    path('payouts/request/', request_early_payout, name='request_early_payout'),
    path('payouts/settings/', update_payout_settings, name='update_payout_settings'),
    path('payouts/api/validate-address/', validate_address_api, name='validate_address_api'),
    path('payouts/api/fee-estimate/', fee_estimate_api, name='fee_estimate_api'),
]
