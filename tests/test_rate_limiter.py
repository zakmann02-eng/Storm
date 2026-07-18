import time

import pytest

from storm.rate_limiter import TokenBucketRateLimiter


def test_burst_is_immediate():
    limiter = TokenBucketRateLimiter(rate=10, burst=3)
    start = time.monotonic()
    for _ in range(3):
        limiter.acquire()
    assert time.monotonic() - start < 0.05


def test_blocks_once_bucket_is_empty():
    limiter = TokenBucketRateLimiter(rate=20, burst=1)
    limiter.acquire()
    start = time.monotonic()
    limiter.acquire()
    elapsed = time.monotonic() - start
    assert elapsed >= 0.04  # ~1/20s refill wait, with slack for scheduling jitter


def test_rejects_invalid_params():
    with pytest.raises(ValueError):
        TokenBucketRateLimiter(rate=0, burst=1)
    with pytest.raises(ValueError):
        TokenBucketRateLimiter(rate=1, burst=0)


def test_rejects_request_larger_than_capacity():
    limiter = TokenBucketRateLimiter(rate=1, burst=2)
    with pytest.raises(ValueError):
        limiter.acquire(tokens=3)
