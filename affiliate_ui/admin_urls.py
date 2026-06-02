from django.urls import path

from .views.admin_views import (
    affiliate_approve,
    affiliate_assign_manager,
    affiliate_detail,
    affiliate_list,
    affiliate_reject,
    affiliate_suspend,
)

app_name = 'affiliate_admin'

urlpatterns = [
    path('', affiliate_list, name='list'),
    path('<int:pk>/', affiliate_detail, name='detail'),
    path('<int:pk>/approve/', affiliate_approve, name='approve'),
    path('<int:pk>/reject/', affiliate_reject, name='reject'),
    path('<int:pk>/suspend/', affiliate_suspend, name='suspend'),
    path('<int:pk>/assign-manager/', affiliate_assign_manager, name='assign_manager'),
]
