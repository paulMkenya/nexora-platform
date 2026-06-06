from django.urls import path

from impersonation import views

app_name = 'impersonation'

urlpatterns = [
    path('start/<int:user_id>/', views.impersonate_start, name='start'),
    path('stop/', views.impersonate_stop, name='stop'),
    path('log/', views.impersonation_log, name='log'),
]
