"""SAFE local preview settings — isolated dev stack, NOT production.

Used only by the manual preview container (DJANGO_SETTINGS_MODULE=
project.settings.preview). DB/Redis come from env (DATABASE_URL / REDIS_URL),
which the preview stack points at a throwaway Postgres/Redis — never prod.
Not committed; test runs keep using project.settings (-> prod.py).
"""
import os

from .base import *  # noqa

SECRET_KEY = os.environ['DJ_SECRET_KEY']
DEBUG = True
ALLOWED_HOSTS = ['*']
CSRF_TRUSTED_ORIGINS = ['http://localhost:8001', 'http://127.0.0.1:8001']

# Plain static storage so {% static %} serves via runserver finders with no
# collectstatic/manifest step.
STATICFILES_STORAGE = 'django.contrib.staticfiles.storage.StaticFilesStorage'
