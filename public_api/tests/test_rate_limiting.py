"""Tests for per-API-key rate limiting."""
import pytest
from django.core.cache import cache
from django.test import RequestFactory

from public_api.throttling import APIKeyThrottle


@pytest.mark.django_db
class TestAPIKeyThrottle:
    def setup_method(self):
        cache.clear()

    def teardown_method(self):
        cache.clear()

    def _make_request(self, api_key):
        factory = RequestFactory()
        req = factory.get('/')
        req._api_key = api_key
        return req

    def test_throttle_allows_within_limit(self, api_key):
        """Requests within rate limit are allowed."""
        from unittest.mock import MagicMock
        throttle = APIKeyThrottle()
        view = MagicMock()
        req = self._make_request(api_key)
        # First request should always be allowed
        assert throttle.allow_request(req, view) is True

    def test_throttle_blocks_after_limit(self, api_key):
        """Throttle blocks after exhausting the key's requests_per_hour."""
        from unittest.mock import MagicMock

        # Set a very low rate for testing
        api_key.requests_per_hour = 2
        api_key.save(update_fields=['requests_per_hour'])

        view = MagicMock()
        allowed_count = 0

        for _ in range(5):
            throttle = APIKeyThrottle()
            req = self._make_request(api_key)
            if throttle.allow_request(req, view):
                allowed_count += 1

        # Should allow exactly 2 requests before blocking
        assert allowed_count == 2

    def test_throttle_skips_non_api_key_requests(self, db):
        """Throttle passes through when no API key auth is present."""
        from unittest.mock import MagicMock
        throttle = APIKeyThrottle()
        view = MagicMock()
        factory = RequestFactory()
        req = factory.get('/')
        # No _api_key attribute → throttle passes through
        assert throttle.allow_request(req, view) is True

    def test_different_keys_have_separate_buckets(self, admin_user, api_key):
        """Two different API keys have independent rate-limit buckets."""
        from unittest.mock import MagicMock

        from public_api.models import APIKey
        from django.contrib.auth import get_user_model
        User = get_user_model()
        user2 = User.objects.create_user(username='throttle_user2', password='pass')
        api_key2 = APIKey.generate(user=user2, name='Key2', requests_per_hour=1)

        api_key.requests_per_hour = 1
        api_key.save(update_fields=['requests_per_hour'])

        view = MagicMock()

        # Exhaust key1
        throttle1 = APIKeyThrottle()
        req1 = self._make_request(api_key)
        throttle1.allow_request(req1, view)

        # key2 should still be allowed (separate bucket)
        throttle2 = APIKeyThrottle()
        req2 = self._make_request(api_key2)
        assert throttle2.allow_request(req2, view) is True
