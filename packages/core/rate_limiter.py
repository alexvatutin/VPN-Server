from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass
class TokenBucket:
    capacity: int
    refill_rate: float
    tokens: float
    last_refill: float

    @classmethod
    def create(cls, capacity: int, refill_rate: float) -> "TokenBucket":
        now = time.monotonic()
        return cls(capacity=capacity, refill_rate=refill_rate, tokens=capacity, last_refill=now)

    def allow(self, amount: int = 1) -> bool:
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
        self.last_refill = now
        if self.tokens >= amount:
            self.tokens -= amount
            return True
        return False


class InMemoryRateLimiter:
    def __init__(self, capacity: int, refill_rate: float) -> None:
        self.capacity = capacity
        self.refill_rate = refill_rate
        self.buckets: dict[str, TokenBucket] = {}

    def allow(self, key: str, amount: int = 1) -> bool:
        bucket = self.buckets.get(key)
        if not bucket:
            bucket = TokenBucket.create(self.capacity, self.refill_rate)
            self.buckets[key] = bucket
        return bucket.allow(amount)
