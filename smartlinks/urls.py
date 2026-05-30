from django.urls import path

from .views import smart_link

urlpatterns = [
    path('sl/<slug:alias>', smart_link, name='smart-link'),
]
