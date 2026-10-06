"""Maps & Location System Phase 27 — Map Billing & Quota Safety.

"Do not repeatedly call geocoding/routes APIs unnecessarily. Cache/reuse
appropriate internal results where permitted by the provider's terms."
A minimal, single-process, thread-safe TTL cache — no external cache
infrastructure needed for a single backend process, the same "simplest
model, no unnecessary infrastructure" discipline already applied to the
service-area work (Phase 14). Used by location_search.py (Photon) and
routing.py (OSRM) to avoid repeat calls to the same free, shared,
rate-limited providers for the same query/coordinate/route.
"""

import threading
import time
from typing import Generic, TypeVar

K = TypeVar("K")
V = TypeVar("V")


class TTLCache(Generic[K, V]):
    def __init__(self, ttl_seconds: float, max_entries: int = 500):
        self._ttl_seconds = ttl_seconds
        self._max_entries = max_entries
        self._lock = threading.Lock()
        self._store: dict[K, tuple[float, V]] = {}

    def get(self, key: K) -> tuple[bool, V | None]:
        """Returns (hit, value) rather than just a bare value — a cached
        value that is itself None (e.g. "no place found at this
        coordinate") must stay distinguishable from a cache miss."""
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return False, None
            expires_at, value = entry
            if time.monotonic() >= expires_at:
                del self._store[key]
                return False, None
            return True, value

    def set(self, key: K, value: V) -> None:
        with self._lock:
            if key not in self._store and len(self._store) >= self._max_entries:
                # Bounded, not unbounded growth — drops one arbitrary
                # entry (oldest-inserted, per dict ordering) rather than
                # letting this grow forever under sustained unique traffic.
                oldest_key = next(iter(self._store))
                del self._store[oldest_key]
            self._store[key] = (time.monotonic() + self._ttl_seconds, value)
