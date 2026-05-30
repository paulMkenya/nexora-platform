from django.urls import path

from . import views

app_name = 'advertiser_ui'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('offers/', views.offers, name='offers'),
    path('conversions/', views.conversions, name='conversions'),
    path('conversions/bulk/', views.bulk_action, name='conversions_bulk'),
    path('conversions/export/', views.export_csv, name='conversions_export'),
    path('postbacks/', views.postbacks, name='postbacks'),
    path('postbacks/regenerate/', views.regenerate_secret, name='postbacks_regenerate'),
    path('wallet/', views.wallet, name='wallet'),
    path('settings/', views.settings_view, name='settings'),
    path('logout/', views.advertiser_logout, name='logout'),
]
