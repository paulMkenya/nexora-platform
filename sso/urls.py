"""Autologin routes.

The path is always registered, and the VIEW decides — it raises Http404 while
the feature is disabled, so a probe gets the same answer as any nonexistent
path and learns nothing (never 403, which would confirm the feature exists).

An earlier version built `urlpatterns` conditionally on the flag. That read
settings at import time, which meant the routing table could not be changed
without a process restart and could not be exercised in a test at all — a
security flag whose "off" state is untestable is not a state you can trust.
The 404 is checked on every request instead, which is both testable and
impossible to leave stale.
"""
from django.urls import path

from .views import redeem

app_name = 'sso'

urlpatterns = [
    path('autologin/', redeem, name='autologin_redeem'),
]
