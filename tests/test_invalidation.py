"""Tests for explicit invalidation and cache clearing behavior."""

from __future__ import annotations

import pytest

from shipsy_cache import TieredCache
from tests.support import InMemoryTestL2


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
