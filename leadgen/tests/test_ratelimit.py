"""Tests for the client-side token bucket (leadgen/ratelimit.py)."""
import time
from unittest.mock import patch

import pytest
from django.core.cache import cache

from leadgen.ratelimit import TokenBucket


@pytest.mark.django_db
class TestTokenBucket:
    def setup_method(self):
        cache.clear()

    def teardown_method(self):
        cache.clear()

    def test_rejects_non_positive_capacity(self):
        with pytest.raises(ValueError):
            TokenBucket('k', capacity=0, refill_tokens=1, refill_seconds=1)

    def test_rejects_non_positive_refill_seconds(self):
        with pytest.raises(ValueError):
            TokenBucket('k', capacity=5, refill_tokens=1, refill_seconds=0)

    def test_fresh_bucket_starts_full(self):
        bucket = TokenBucket('fresh', capacity=5, refill_tokens=1, refill_seconds=1)
        for _ in range(5):
            assert bucket.try_acquire(1) is True

    def test_exhausted_bucket_rejects(self):
        bucket = TokenBucket('exhaust', capacity=3, refill_tokens=1, refill_seconds=1)
        assert bucket.try_acquire(3) is True
        assert bucket.try_acquire(1) is False

    def test_try_acquire_n_greater_than_capacity_never_succeeds_when_partially_drained(self):
        bucket = TokenBucket('big-n', capacity=5, refill_tokens=1, refill_seconds=1)
        assert bucket.try_acquire(1) is True  # 4 left
        assert bucket.try_acquire(5) is False  # only 4 available

    def test_refill_over_time_restores_tokens(self):
        bucket = TokenBucket('refill', capacity=5, refill_tokens=5, refill_seconds=1)
        assert bucket.try_acquire(5) is True
        assert bucket.try_acquire(1) is False

        now = time.time()
        with patch('leadgen.ratelimit.time.time', return_value=now + 1.0):
            # 1s elapsed at 5 tokens/sec refill -> bucket back to full (capped)
            assert bucket.try_acquire(5) is True

    def test_refill_is_capped_at_capacity(self):
        bucket = TokenBucket('cap', capacity=2, refill_tokens=100, refill_seconds=1)
        now = time.time()
        with patch('leadgen.ratelimit.time.time', return_value=now + 1000):
            # Huge elapsed time shouldn't overflow past capacity
            assert bucket.try_acquire(3) is False
            assert bucket.try_acquire(2) is True

    def test_acquire_blocks_then_succeeds_once_refilled(self):
        bucket = TokenBucket('block', capacity=1, refill_tokens=1, refill_seconds=1, max_wait=5.0)
        assert bucket.try_acquire(1) is True  # drain it

        call_count = {'n': 0}
        real_time = time.time()

        def fake_time():
            # First few calls report no elapsed time, then jump forward enough
            # to refill — proves acquire() actually loops rather than
            # succeeding immediately on an empty bucket.
            call_count['n'] += 1
            return real_time if call_count['n'] < 3 else real_time + 1.5

        with patch('leadgen.ratelimit.time.time', side_effect=fake_time), \
             patch('leadgen.ratelimit.time.sleep', return_value=None):
            bucket.acquire(1)  # must not raise

    def test_acquire_raises_timeout_when_never_refilled(self):
        bucket = TokenBucket('timeout', capacity=1, refill_tokens=1, refill_seconds=9999, max_wait=0.5)
        assert bucket.try_acquire(1) is True  # drain it

        with patch('leadgen.ratelimit.time.sleep', return_value=None):
            with pytest.raises(TimeoutError):
                bucket.acquire(1)

    def test_for_buyer_derives_config_from_buyer_fields(self, buyer):
        bucket = TokenBucket.for_buyer(buyer)
        assert bucket.key == f'leadgen_bucket:buyer:{buyer.pk}'
        assert bucket.capacity == buyer.rate_limit_burst
        assert bucket.refill_rate == buyer.rate_limit_refill_tokens / buyer.rate_limit_refill_seconds

    def test_separate_keys_have_independent_buckets(self):
        b1 = TokenBucket('bucket-a', capacity=1, refill_tokens=1, refill_seconds=1)
        b2 = TokenBucket('bucket-b', capacity=1, refill_tokens=1, refill_seconds=1)
        assert b1.try_acquire(1) is True
        assert b2.try_acquire(1) is True  # independent — not affected by b1's drain
