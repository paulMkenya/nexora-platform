from django.apps import AppConfig


class PublicApiConfig(AppConfig):
    name = 'public_api'
    default_auto_field = 'django.db.models.BigAutoField'

    def ready(self):
        import public_api.signals  # noqa: F401
