"""Global pytest fixtures.

Test isolation for the shared Redis. Django ``TestCase`` wraps each test in a
transaction and rolls it back, and it reuses row ids across tests — but Redis is
NOT transactional, so anything written there leaks between tests and causes
order-dependent failures. Two distinct caches live in the same Redis db:

  * the raw ``offers:{id}`` records written by ``offer.tasks.cache_offers`` and
    read by ``tracker.dao.TrackerCache`` (a plain ``redis.set`` — Django's
    ``cache.clear()`` can't touch it because it bypasses the cache key prefix);
  * Django's own cache, which under the CI/prod settings is the RedisCache
    backend (locally it is LocMemCache).

Flushing Redis (and Django's cache) around every test gives each test a clean
slate — the isolation the suite was missing and the real cause of the
"passes in isolation, fails in the monolithic run" TrackerCache failures.
"""
import pytest
import redis
from django.conf import settings
from django.core.cache import cache


@pytest.fixture(autouse=True)
def _isolate_caches():
    conn = redis.Redis.from_url(settings.REDIS_URL)

    def _reset():
        try:
            conn.flushdb()
        except redis.exceptions.RedisError:
            # No Redis reachable (e.g. a pure unit run) — nothing to isolate.
            pass
        try:
            cache.clear()
        except Exception:  # noqa: BLE001 — cache backend may be unreachable; ignore in tests
            pass

    _reset()
    yield
    _reset()
