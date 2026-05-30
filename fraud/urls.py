from django.urls import path
from . import views

app_name = 'fraud'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('whitelist/add/', views.whitelist_add, name='whitelist-add'),
    path('whitelist/remove/<int:pk>/', views.whitelist_remove, name='whitelist-remove'),
]
