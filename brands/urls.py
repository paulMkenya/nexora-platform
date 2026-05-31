from django.urls import path
from brands.views import admin_views

app_name = 'brands_admin'

urlpatterns = [
    path('', admin_views.brand_list, name='brand_list'),
    path('new/', admin_views.brand_create, name='brand_create'),
    path('<int:pk>/edit/', admin_views.brand_edit, name='brand_edit'),
    path('<int:pk>/delete/', admin_views.brand_delete, name='brand_delete'),
    path('<int:pk>/setup/', admin_views.brand_setup, name='brand_setup'),
]
