"""Tests for stale serving and L2 degradation paths."""

from __future__ import annotations

import asyncio
from typing import Any, Optional

import pytest

from shipsy_cache import FactoryError, L2UnavailableError, TieredCache
from shipsy_cache.l2.base import L2Backend


class FlakyL2(L2Backend):
    """L2 backend that can be configured to fail operations."""

    def __init__(self, fail_reads: bool = True, fail_writes: bool = True) -> None:
        """Initialize failure flags."""

        self.fail_reads = fail_reads
        self.fail_writes = fail_writes
        self.storage: dict[str, Any] = {}

    async def get(self, key: str) -> Optional[Any]:
        """Raise or return a stored value."""

        if self.fail_reads:
            raise L2UnavailableError("read failure")
        return self.storage.get(key)

    async def set(self, key: str, value: Any, ttl_seconds: float) -> None:
        """Raise or store the provided value."""

        if self.fail_writes:
            raise L2UnavailableError("write failure")
        self.storage[key] = value

    async def delete(self, key: str) -> None:
        """Delete a key if present."""

        self.storage.pop(key, None)

    async def clear(self) -> None:
        """Clear all stored values."""

        self.storage.clear()

    async def ping(self) -> bool:
        """Return whether reads are operational."""

        return not self.fail_reads


@pytest.mark.asyncio
async def test_serves_stale_when_factory_fails() -> None:
    """An expired L1 value within the grace period should be served on failure."""

    cache = TieredCache(default_ttl=0.05, grace_period=1)
    await cache.set("rates", {"amount": 99}, ttl=0.05)
    await asyncio.sleep(0.1)

    async def failing_factory() -> dict[str, int]:
        raise RuntimeError("upstream failure")

    value = await cache.getOrSet("rates", failing_factory, ttl=60)

    assert value == {"amount": 99}


@pytest.mark.asyncio
async def test_raises_when_stale_beyond_grace_period() -> None:
    """Expired values outside the grace window should raise ``FactoryError``."""

    cache = TieredCache(default_ttl=0.05, grace_period=0.05)
    await cache.set("rates", {"amount": 99}, ttl=0.05)
    await asyncio.sleep(0.2)

    async def failing_factory() -> dict[str, int]:
        raise RuntimeError("upstream failure")

    with pytest.raises(FactoryError):
        await cache.getOrSet("rates", failing_factory, ttl=60)


@pytest.mark.asyncio
async def test_l2_unavailable_still_serves_from_l1() -> None:
    """L1 hits should continue to work even when L2 reads fail."""

    l2 = FlakyL2(fail_reads=True, fail_writes=False)
    cache = TieredCache(l2_backend=l2)
    await cache.set("inventory", {"count": 7}, ttl=60)

    assert await cache.get("inventory") == {"count": 7}


@pytest.mark.asyncio
async def test_l2_unavailable_factory_succeeds_writes_l1() -> None:
    """Factory success should still populate L1 when L2 writes are unavailable."""

    l2 = FlakyL2(fail_reads=True, fail_writes=True)
    cache = TieredCache(l2_backend=l2)

    async def factory() -> str:
        return "fallback"

    result = await cache.getOrSet("outage", factory, ttl=60)

    assert result == "fallback"
    assert cache._l1.get(cache._namespaced_key("outage")) == "fallback"
