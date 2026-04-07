"""Tests for polymarket_sdk.cache.TTLCache."""
from __future__ import annotations

import time

import pytest

from polymarket_sdk.cache import TTLCache


class TestTTLCache:
    def test_set_and_get(self) -> None:
        cache = TTLCache()
        cache.set("key", "value")
        assert cache.get("key") == "value"

    def test_get_missing_key_returns_none(self) -> None:
        cache = TTLCache()
        assert cache.get("nonexistent") is None

    def test_expired_entry_returns_none(self) -> None:
        cache = TTLCache(default_ttl=1)
        cache.set("key", "value", ttl=0)
        # ttl=0 means already expired
        assert cache.get("key") is None

    def test_invalidate_removes_entry(self) -> None:
        cache = TTLCache()
        cache.set("key", "value")
        cache.invalidate("key")
        assert cache.get("key") is None

    def test_invalidate_missing_key_is_noop(self) -> None:
        cache = TTLCache()
        cache.invalidate("does_not_exist")  # should not raise

    def test_clear_removes_all_entries(self) -> None:
        cache = TTLCache()
        cache.set("a", 1)
        cache.set("b", 2)
        cache.set("c", 3)
        cache.clear()
        assert cache.get("a") is None
        assert cache.get("b") is None
        assert len(cache) == 0

    def test_len_counts_live_entries(self) -> None:
        cache = TTLCache()
        cache.set("a", 1)
        cache.set("b", 2)
        assert len(cache) == 2

    def test_contains_operator(self) -> None:
        cache = TTLCache()
        cache.set("key", "val")
        assert "key" in cache
        assert "other" not in cache

    def test_custom_ttl_overrides_default(self) -> None:
        cache = TTLCache(default_ttl=999)
        # Setting ttl=0 should expire immediately.
        cache.set("key", "value", ttl=0)
        assert cache.get("key") is None

    def test_stats_returns_size(self) -> None:
        cache = TTLCache()
        cache.set("a", 1)
        stats = cache.stats()
        assert stats["size"] == 1
        assert "default_ttl" in stats

    def test_stores_complex_values(self) -> None:
        cache = TTLCache()
        data = [{"id": "m1", "price": 0.45}, {"id": "m2", "price": 0.6}]
        cache.set("markets", data)
        assert cache.get("markets") == data
