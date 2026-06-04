from django.urls import path

from .views.advertiser_views import (
    advertiser_approve,
    advertiser_list,
    advertiser_reject,
    advertiser_suspend,
)

app_name = 'advertisers_admin'

urlpatterns = [
    path('', advertiser_list, name='list'),
    path('<int:pk>/approve/', advertiser_approve, name='approve'),
    path('<int:pk>/reject/', advertiser_reject, name='reject'),
    path('<int:pk>/suspend/', advertiser_suspend, name='suspend'),
]
