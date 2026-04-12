"""Tests for explicit invalidation and cache clearing behavior."""

from __future__ import annotations

import pytest

from shipsy_cache import L2UnavailableError, TieredCache
from shipsy_cache.l2.base import L2Backend, L2CacheEntry
from tests.support import InMemoryTestL2


class DeleteOrClearFailL2(L2Backend):
    """Backend that can fail correctness-sensitive invalidation operations."""

    def __init__(self, fail_delete: bool = False, fail_clear: bool = False) -> None:
        self.fail_delete = fail_delete
        self.fail_clear = fail_clear
        self.storage: dict[str, object] = {}

    async def get_entry(self, key: str) -> L2CacheEntry | None:
        value = self.storage.get(key)
        if value is None:
            return None
        return L2CacheEntry(value=value, remaining_ttl_seconds=None)

    async def set(self, key: str, value: object, ttl_seconds: float) -> None:
        self.storage[key] = value

    async def delete(self, key: str) -> None:
        if self.fail_delete:
            raise L2UnavailableError("delete failed")
        self.storage.pop(key, None)

    async def clear(self) -> None:
        if self.fail_clear:
            raise L2UnavailableError("clear failed")
        self.storage.clear()

    async def ping(self) -> bool:
        return True


@pytest.mark.asyncio
async def test_invalidate_missing_key_is_noop() -> None:
    """Invalidating a missing key should not raise errors."""

    cache = TieredCache(l2_backend=InMemoryTestL2())

    await cache.invalidate("missing")

    assert await cache.get("missing") is None


@pytest.mark.asyncio
async def test_clear_removes_all_entries() -> None:
    """Clearing the cache should empty both tiers."""

    cache = TieredCache(l2_backend=InMemoryTestL2())
    await cache.set("a", 1, ttl=60)
    await cache.set("b", 2, ttl=60)

    await cache.clear()

    assert cache.stats()["l1"]["size"] == 0
    assert await cache.get("a") is None
    assert await cache.get("b") is None


@pytest.mark.asyncio
async def test_namespace_isolation_between_caches() -> None:
    """Two cache instances should isolate keys using namespaces."""

    shared_l2 = InMemoryTestL2()
    cache_a = TieredCache(l2_backend=shared_l2, namespace="a")
    cache_b = TieredCache(l2_backend=shared_l2, namespace="b")

    await cache_a.set("shared-key", "value-a", ttl=60)
    await cache_b.set("shared-key", "value-b", ttl=60)

    assert await cache_a.get("shared-key") == "value-a"
    assert await cache_b.get("shared-key") == "value-b"


@pytest.mark.asyncio
async def test_invalidate_fails_before_mutating_l1_when_l2_delete_fails() -> None:
    """Invalidation should fail fast and keep local state intact if L2 delete fails."""

    l2 = DeleteOrClearFailL2(fail_delete=True)
    cache = TieredCache(l2_backend=l2)
    await cache.set("customer", {"tier": "gold"}, ttl=60)

    with pytest.raises(L2UnavailableError):
        await cache.invalidate("customer")

    assert cache._l1.get(cache._namespaced_key("customer")) == {"tier": "gold"}


@pytest.mark.asyncio
async def test_clear_fails_before_mutating_l1_when_l2_clear_fails() -> None:
    """Clear should fail fast and preserve local L1 entries if L2 clear fails."""

    l2 = DeleteOrClearFailL2(fail_clear=True)
    cache = TieredCache(l2_backend=l2)
    await cache.set("a", 1, ttl=60)
    await cache.set("b", 2, ttl=60)

    with pytest.raises(L2UnavailableError):
        await cache.clear()

    assert cache._l1.get(cache._namespaced_key("a")) == 1
    assert cache._l1.get(cache._namespaced_key("b")) == 2
