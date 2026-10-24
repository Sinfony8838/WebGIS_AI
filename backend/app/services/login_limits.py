"""Process-local login admission with bounded, expiring identity buckets.

Only the HTTP boundary may interpret proxy headers. This module receives the
already-selected client IP and never reads headers or stores raw identities.
"""
from __future__ import annotations

import hashlib
import math
import time
from collections import OrderedDict, deque
from threading import Lock
from typing import Callable


class LoginLimited(Exception):
    def __init__(self, retry_after: int):
        self.retry_after = max(1, retry_after)


class LoginLimits:
    def __init__(
        self, *, account_limit: int = 10, ip_limit: int = 1200,
        global_limit: int = 2400, window_seconds: int = 300,
        max_buckets: int = 8192, clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if min(account_limit, ip_limit, global_limit, window_seconds) < 1 or max_buckets < 3:
            raise ValueError("Invalid login rate limit")
        self.account_limit = account_limit
        self.ip_limit = ip_limit
        self.global_limit = global_limit
        self.window_seconds = window_seconds
        self.max_buckets = max_buckets
        self._clock = clock
        self._lock = Lock()
        self._buckets: OrderedDict[str, deque[float]] = OrderedDict()

    @staticmethod
    def _key(kind: str, value: str) -> str:
        return kind + ":" + hashlib.sha256(value.encode("utf-8")).hexdigest()

    def check(self, normalized_account: str, ip_address: str) -> None:
        limits = (
            ("global", self.global_limit),
            (self._key("account", normalized_account), self.account_limit),
            (self._key("ip", ip_address), self.ip_limit),
        )
        with self._lock:
            now = self._clock()
            cutoff = now - self.window_seconds
            # Ordered by the last admitted attempt. Never evict a live bucket
            # to make room: rotating identities must not reset other limits.
            while self._buckets:
                first = next(iter(self._buckets))
                if self._buckets[first][-1] > cutoff:
                    break
                self._buckets.popitem(last=False)
            for key, limit in limits:
                bucket = self._buckets.get(key)
                if bucket is None:
                    continue
                while bucket and bucket[0] <= cutoff:
                    bucket.popleft()
                if len(bucket) >= limit:
                    raise LoginLimited(math.ceil(bucket[0] + self.window_seconds - now))
            added = sum(key not in self._buckets for key, _ in limits)
            if len(self._buckets) + added > self.max_buckets:
                first = next(iter(self._buckets.values()))
                raise LoginLimited(math.ceil(first[-1] + self.window_seconds - now))
            for key, _ in limits:
                self._buckets.setdefault(key, deque()).append(now)
                self._buckets.move_to_end(key)
