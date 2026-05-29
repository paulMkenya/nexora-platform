from django.urls import path

from .views import dashboard

app_name = 'advertiser'

urlpatterns = [
    path('', dashboard, name='dashboard'),
]
