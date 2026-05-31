from rest_framework.throttling import SimpleRateThrottle


class APIKeyThrottle(SimpleRateThrottle):
    """
    Per-API-key rate limiter.  Rate is read from APIKey.requests_per_hour.
    Falls through (returns True) when the request was not authenticated via
    an API key so other throttles can handle it.
    """

    scope = 'api_key'

    def allow_request(self, request, view):
        api_key = getattr(request, '_api_key', None)
        if api_key is None:
            return True
        self.rate = f'{api_key.requests_per_hour}/hour'
        self.num_requests, self.duration = self.parse_rate(self.rate)
        return super().allow_request(request, view)

    def get_cache_key(self, request, view):
        api_key = getattr(request, '_api_key', None)
        if api_key is None:
            return None
        return f'throttle_apikey_{api_key.pk}'
