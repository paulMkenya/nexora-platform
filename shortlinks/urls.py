from django.urls import path

from .views import go

urlpatterns = [
    path('go/<str:slug>', go, name='short-link'),
]
