"""Tests for core cache hit and miss behavior."""

from __future__ import annotations

from typing import Any, Optional

import pytest

from shipsy_cache import TieredCache
from shipsy_cache.l2.base import L2Backend
from tests.support import InMemoryTestL2


class TrackingMemoryL2(InMemoryTestL2):
    """Memory L2 backend that counts read calls."""

    def __init__(self) -> None:
        """Initialize counters and storage."""

        super().__init__()
        self.get_calls = 0

    async def get(self, key: str) -> Optional[Any]:
        """Count and delegate L2 reads."""

        self.get_calls += 1
        return await super().get(key)


@pytest.mark.asyncio
async def test_get_returns_none_on_cold_cache() -> None:
    """Cold cache lookups should return ``None``."""

    cache = TieredCache(l2_backend=InMemoryTestL2())

    assert await cache.get("missing") is None


@pytest.mark.asyncio
async def test_set_then_get_returns_value() -> None:
    """Values written to the cache should be retrievable."""

    cache = TieredCache(l2_backend=InMemoryTestL2())
    await cache.set("customer", {"name": "Asha"}, ttl=60)

    assert await cache.get("customer") == {"name": "Asha"}


@pytest.mark.asyncio
async def test_l1_hit_does_not_reach_l2() -> None:
    """Once a value is in L1, a read should not query L2."""

    l2 = TrackingMemoryL2()
    cache = TieredCache(l2_backend=l2)
    await cache.set("product", "cached", ttl=60)

    l2.get_calls = 0
    assert await cache.get("product") == "cached"
    assert l2.get_calls == 0


@pytest.mark.asyncio
async def test_l2_hit_populates_l1() -> None:
    """Values fetched from L2 should hydrate L1."""

    cache = TieredCache(l2_backend=InMemoryTestL2())
    namespaced_key = cache._namespaced_key("invoice")
    await cache._l2.set(namespaced_key, {"total": 123}, ttl_seconds=60)

    assert await cache.get("invoice") == {"total": 123}
    assert cache._l1.get(namespaced_key) == {"total": 123}


@pytest.mark.asyncio
async def test_get_or_set_calls_factory_on_miss() -> None:
    """Factory should run on a cold key."""

    calls = 0

    async def factory() -> str:
        nonlocal calls
        calls += 1
        return "built"

    cache = TieredCache(l2_backend=InMemoryTestL2())
    value = await cache.getOrSet("build-key", factory, ttl=60)

    assert value == "built"
    assert calls == 1


@pytest.mark.asyncio
async def test_get_or_set_does_not_call_factory_on_hit() -> None:
    """Factory should not run when a key is already cached."""

    calls = 0

    async def factory() -> str:
        nonlocal calls
        calls += 1
        return "fresh"

    cache = TieredCache(l2_backend=InMemoryTestL2())
    await cache.set("warm", "existing", ttl=60)

    value = await cache.getOrSet("warm", factory, ttl=60)

    assert value == "existing"
    assert calls == 0


@pytest.mark.asyncio
async def test_invalidate_removes_from_both_tiers() -> None:
    """Invalidation should remove the key from L1 and L2."""

    cache = TieredCache(l2_backend=InMemoryTestL2())
    await cache.set("session", {"active": True}, ttl=60)

    await cache.invalidate("session")

    assert await cache.get("session") is None
    assert cache._l1.get(cache._namespaced_key("session")) is None
    assert await cache._l2.get(cache._namespaced_key("session")) is None
