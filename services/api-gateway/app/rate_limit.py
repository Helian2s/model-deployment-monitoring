from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Deque


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    retry_after_seconds: int = 0


class FixedWindowRateLimiter:
    def __init__(self, limit_per_minute: int) -> None:
        self._limit = limit_per_minute
        self._events: dict[str, Deque[float]] = defaultdict(deque)

    def check(self, key: str) -> RateLimitDecision:
        if self._limit <= 0:
            return RateLimitDecision(allowed=True)

        now = time.monotonic()
        window_start = now - 60
        events = self._events[key]
        while events and events[0] < window_start:
            events.popleft()

        if len(events) >= self._limit:
            retry_after = max(1, int(60 - (now - events[0])))
            return RateLimitDecision(allowed=False, retry_after_seconds=retry_after)

        events.append(now)
        return RateLimitDecision(allowed=True)
