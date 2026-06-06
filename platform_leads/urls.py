"""Owner-only sales pipeline routes, mounted at /admin/platform-leads/."""
from django.urls import path

from platform_leads import views

app_name = 'platform_leads_admin'

urlpatterns = [
    path('', views.pipeline, name='pipeline'),
    path('settings/', views.settings_view, name='settings'),
    path('<int:pk>/', views.lead_detail, name='lead_detail'),
    path('<int:pk>/stage/', views.update_stage, name='update_stage'),
    path('<int:pk>/note/', views.add_note, name='add_note'),
    path('<int:pk>/contacted/', views.mark_contacted, name='mark_contacted'),
]
