from django.urls import path

from leads import views

app_name = 'leads_admin'

urlpatterns = [
    path('', views.lead_list, name='lead_list'),
    path('<int:pk>/stage/', views.lead_update_stage, name='lead_update_stage'),
    path('<int:pk>/note/', views.lead_add_note, name='lead_add_note'),
]
