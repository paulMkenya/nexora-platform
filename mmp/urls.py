from django.urls import path
from . import views

app_name = 'mmp'

urlpatterns = [
    path('callback/<str:vendor>/', views.mmp_callback, name='callback'),
]
