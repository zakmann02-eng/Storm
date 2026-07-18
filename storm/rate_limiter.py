"""Thread-safe token-bucket rate limiter.

Storm shares a single Polymarket API key/account with Colossus (a separate
bot covering most sports leagues, running from its own repo and Railway
project). This limiter only tracks Storm's own outbound request volume - it
caps Storm to a conservative slice of the account's overall rate limit so a
burst from Storm can't starve or trip a ban on the shared key. It does not,
and cannot, coordinate directly with Colossus's process; keep
STORM_MAX_REQUESTS_PER_SECOND low enough that Storm's share plus Colossus's
own usage stays under Polymarket's documented per-key limit.

One instance should be shared by every client that talks to Polymarket
(Gamma API reads and CLOB order calls alike) so all of Storm's traffic is
metered against a single ceiling.
"""

from __future__ import annotations

import threading
import time


class TokenBucketRateLimiter:
    def __init__(self, rate: float, burst: int):
        if rate <= 0:
            raise ValueError("rate must be positive")
        if burst < 1:
            raise ValueError("burst must be at least 1")
        self._rate = rate
        self._capacity = float(burst)
        self._tokens = float(burst)
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        if elapsed > 0:
            self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
            self._last_refill = now

    def acquire(self, tokens: float = 1.0) -> None:
        """Block until `tokens` are available, then consume them."""
        if tokens > self._capacity:
            raise ValueError("requested tokens exceed bucket capacity")
        while True:
            with self._lock:
                self._refill()
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return
                deficit = tokens - self._tokens
                wait_time = deficit / self._rate
            time.sleep(wait_time)
