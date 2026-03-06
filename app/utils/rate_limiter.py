from __future__ import annotations

import time


class RateLimiter:
    def __init__(self, interval_seconds: float) -> None:
        self.interval_seconds = max(0.0, interval_seconds)
        self._last_at = 0.0

    def wait(self) -> None:
        now = time.monotonic()
        delta = now - self._last_at
        if delta < self.interval_seconds:
            time.sleep(self.interval_seconds - delta)
        self._last_at = time.monotonic()
