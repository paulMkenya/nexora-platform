from django.apps import AppConfig


class SsoConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'sso'
    verbose_name = 'SSO / autologin'

    def ready(self):
        """Announce loudly when the feature is live.

        A bearer-credential login path being enabled should never be something
        you discover by reading settings. If it is on, it says so at WARNING
        with the TTL it will mint, every boot.
        """
        import logging

        from . import config

        if config.is_enabled():
            logging.getLogger(__name__).warning(
                'SSO AUTOLOGIN IS ENABLED — signed bearer links can log users in '
                '(ttl=%ss, ceiling=%ss). Disable SSO_AUTOLOGIN_ENABLED if this is '
                'not deliberate.',
                config.ttl_seconds(), config.TTL_CEILING_SECONDS,
            )
