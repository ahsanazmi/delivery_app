"""Maps & Location System Phase 27 — Map Billing & Quota Safety."""

import time

from app.core.ttl_cache import TTLCache


def test_miss_on_an_unset_key():
    cache: TTLCache[str, str] = TTLCache(ttl_seconds=60)
    hit, value = cache.get("missing")
    assert hit is False
    assert value is None


def test_hit_returns_the_stored_value():
    cache: TTLCache[str, str] = TTLCache(ttl_seconds=60)
    cache.set("key", "value")
    hit, value = cache.get("key")
    assert hit is True
    assert value == "value"


def test_a_cached_none_is_distinguishable_from_a_miss():
    cache: TTLCache[str, str | None] = TTLCache(ttl_seconds=60)
    cache.set("key", None)
    hit, value = cache.get("key")
    assert hit is True
    assert value is None


def test_expires_after_its_ttl():
    cache: TTLCache[str, str] = TTLCache(ttl_seconds=0.01)
    cache.set("key", "value")
    time.sleep(0.02)
    hit, value = cache.get("key")
    assert hit is False
    assert value is None


def test_evicts_an_entry_once_max_entries_is_reached_rather_than_growing_unbounded():
    cache: TTLCache[int, int] = TTLCache(ttl_seconds=60, max_entries=3)
    cache.set(1, 1)
    cache.set(2, 2)
    cache.set(3, 3)
    cache.set(4, 4)

    hits = sum(1 for key in (1, 2, 3, 4) if cache.get(key)[0])
    assert hits == 3
