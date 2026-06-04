from django.urls import path

from . import views
from .registration_views import (
    AdvertiserLoginView,
    register,
    verify_email,
)

app_name = 'advertiser_ui'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('login/', AdvertiserLoginView.as_view(), name='login'),
    path('register/', register, name='register'),
    path('verify-email/<str:token>/', verify_email, name='verify_email'),
    path('offers/', views.offers, name='offers'),
    path('offers/new/', views.offer_create, name='offer_create'),
    path('offers/<int:offer_id>/edit/', views.offer_edit, name='offer_edit'),
    path('offers/<int:offer_id>/status/', views.offer_set_status, name='offer_set_status'),
    path('conversions/', views.conversions, name='conversions'),
    path('conversions/bulk/', views.bulk_action, name='conversions_bulk'),
    path('conversions/export/', views.export_csv, name='conversions_export'),
    path('postbacks/', views.postbacks, name='postbacks'),
    path('mmp/', views.mmp_callbacks, name='mmp_callbacks'),
    path('postbacks/regenerate/', views.regenerate_secret, name='postbacks_regenerate'),
    path('wallet/', views.wallet, name='wallet'),
    path('settings/', views.settings_view, name='settings'),
    path('logout/', views.advertiser_logout, name='logout'),
]
