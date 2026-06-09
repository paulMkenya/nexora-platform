from django.urls import path

from user_profile.views import set_theme

app_name = 'user_profile'

urlpatterns = [
    path('theme/', set_theme, name='set_theme'),
]
