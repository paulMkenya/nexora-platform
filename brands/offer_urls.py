from django.urls import path

from .views.offer_views import (
    offer_create,
    offer_edit,
    offer_list,
    offer_set_status,
)

app_name = 'offers_admin'

urlpatterns = [
    path('', offer_list, name='list'),
    path('new/', offer_create, name='create'),
    path('<int:offer_id>/edit/', offer_edit, name='edit'),
    path('<int:offer_id>/status/', offer_set_status, name='set_status'),
]
