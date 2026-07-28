"""Client-side token bucket rate limiter.

Mirrors whatever rate a buyer documents (LeadBuyer.rate_limit_*) so we stay
under their limit proactively rather than reacting to 429s after the fact —
op-brandy's own policy (60 burst, 5 tokens/2s refill) is the first configured
example.

State lives in Django's cache (Redis in prod — see CACHES in settings), so
it's shared across Celery worker processes rather than per-process. This
intentionally isn't perfectly race-free under concurrent acquires (a plain
get/set, not a Redis-atomic compare-and-swap) — for a client-side safety
margin protecting a third party's rate limit, occasional drift of a token or
two under moderate concurrency is an acceptable tradeoff against the
complexity of a Lua-script-based exact implementation. Bucket capacities in
practice (tens of tokens) comfortably absorb that.
"""
import time

from django.core.cache import cache


class TokenBucket:
    def __init__(self, key: str, capacity: int, refill_tokens: int, refill_seconds: int, max_wait: float = 30.0):
        if capacity <= 0 or refill_seconds <= 0:
            raise ValueError('capacity and refill_seconds must be positive')
        self.key = f'leadgen_bucket:{key}'
        self.capacity = capacity
        self.refill_rate = refill_tokens / refill_seconds  # tokens per second
        self.max_wait = max_wait
        # Cache entries expire well past the time a full bucket could stay
        # idle, so an abandoned key doesn't linger forever.
        self._cache_timeout = max(60, refill_seconds * capacity * 2)

    def _load(self):
        state = cache.get(self.key)
        now = time.time()
        if state is None:
            return {'tokens': float(self.capacity), 'ts': now}
        elapsed = max(0.0, now - state['ts'])
        tokens = min(self.capacity, state['tokens'] + elapsed * self.refill_rate)
        return {'tokens': tokens, 'ts': now}

    def try_acquire(self, n: int = 1) -> bool:
        """Non-blocking. True and consumes n tokens if available, else False
        (bucket state is still refreshed either way)."""
        state = self._load()
        ok = state['tokens'] >= n
        if ok:
            state['tokens'] -= n
        cache.set(self.key, state, timeout=self._cache_timeout)
        return ok

    def acquire(self, n: int = 1) -> None:
        """Blocking — sleeps until n tokens are available. Only call this
        from a background task (Celery), never in a request/response cycle.
        Raises TimeoutError past max_wait so a stuck worker doesn't hang
        forever on a misconfigured or exhausted bucket."""
        waited = 0.0
        step = 0.2
        while not self.try_acquire(n):
            if waited >= self.max_wait:
                raise TimeoutError(f'Rate-limit wait exceeded {self.max_wait}s for {self.key!r}')
            time.sleep(step)
            waited += step

    @classmethod
    def for_buyer(cls, buyer) -> 'TokenBucket':
        return cls(
            key=f'buyer:{buyer.pk}',
            capacity=buyer.rate_limit_burst,
            refill_tokens=buyer.rate_limit_refill_tokens,
            refill_seconds=buyer.rate_limit_refill_seconds,
        )
