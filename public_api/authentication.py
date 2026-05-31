from django.utils import timezone
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed


class APIKeyAuthentication(BaseAuthentication):
    """
    Authenticates requests via 'Authorization: ApiKey <secret>' header.

    On success sets request._api_key so throttling can read the per-key rate.
    Compatible with existing JWT auth — both can be listed in
    DEFAULT_AUTHENTICATION_CLASSES and DRF tries each in order.
    """

    keyword = 'ApiKey'

    def authenticate(self, request):
        auth = request.META.get('HTTP_AUTHORIZATION', '').split()
        if len(auth) != 2 or auth[0].lower() != self.keyword.lower():
            return None

        from public_api.models import APIKey

        try:
            api_key = (
                APIKey.objects.select_related('user')
                .get(secret=auth[1], is_active=True)
            )
        except APIKey.DoesNotExist:
            raise AuthenticationFailed('Invalid or inactive API key.')

        # Fire-and-forget update; never block the request path on this
        APIKey.objects.filter(pk=api_key.pk).update(last_used_at=timezone.now())

        request._api_key = api_key
        return (api_key.user, api_key)

    def authenticate_header(self, request):
        return f'{self.keyword} realm="api"'
