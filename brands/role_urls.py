from django.urls import path

from brands.views.role_views import (
    appoint_brand_admin,
    appoint_manager,
    roles_home,
)

app_name = 'roles_admin'

urlpatterns = [
    path('', roles_home, name='home'),
    path('appoint-brand-admin/', appoint_brand_admin, name='appoint_brand_admin'),
    path('appoint-manager/', appoint_manager, name='appoint_manager'),
]
