from django.urls import path

from brands.views import archived_views

app_name = 'archived_admin'

urlpatterns = [
    path('', archived_views.archived_home, name='home'),

    path('affiliate/<int:pk>/archive/', archived_views.affiliate_archive, name='affiliate_archive'),
    path('affiliate/<int:pk>/restore/', archived_views.affiliate_restore, name='affiliate_restore'),
    path('affiliate/<int:pk>/delete/', archived_views.affiliate_delete, name='affiliate_delete'),

    path('advertiser/<int:pk>/archive/', archived_views.advertiser_archive, name='advertiser_archive'),
    path('advertiser/<int:pk>/restore/', archived_views.advertiser_restore, name='advertiser_restore'),
    path('advertiser/<int:pk>/delete/', archived_views.advertiser_delete, name='advertiser_delete'),

    path('brand/<int:pk>/archive/', archived_views.brand_archive, name='brand_archive'),
    path('brand/<int:pk>/restore/', archived_views.brand_restore, name='brand_restore'),
]
