from django.urls import path

from .views import landing

app_name = 'website'

urlpatterns = [
    path('', landing, name='landing'),
]
