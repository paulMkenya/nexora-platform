from django.apps import AppConfig


class LeadsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'leads'
    verbose_name = 'CRM Leads'

    def ready(self):
        super().ready()
        import leads.signals  # noqa: F401
