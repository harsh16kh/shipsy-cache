"""Tests for cache lifecycle events."""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List

import pytest

from shipsy_cache import FactoryError, TieredCache
from tests.support import InMemoryTestL2


@pytest.mark.asyncio
async def test_cache_hit_event_emitted() -> None:
    """A cache hit should emit a structured hit event."""

    events: List[Dict[str, Any]] = []
    cache = TieredCache(l2_backend=InMemoryTestL2())
    cache.on("cache:hit", events.append)

    await cache.set("order-1", {"status": "ready"})
    value = await cache.get("order-1")

    assert value == {"status": "ready"}
    assert any(event["event"] == "cache:hit" and event["key"] == "order-1" for event in events)


@pytest.mark.asyncio
async def test_cache_miss_event_emitted() -> None:
    """A cold miss should emit a miss event."""

    events: List[Dict[str, Any]] = []
    cache = TieredCache(l2_backend=InMemoryTestL2())
    cache.on("cache:miss", events.append)

    value = await cache.get("missing")

    assert value is None
    assert len(events) == 1
    assert events[0]["event"] == "cache:miss"
    assert events[0]["key"] == "missing"


@pytest.mark.asyncio
async def test_cache_set_event_emitted() -> None:
    """Writes should emit a cache:set event."""

    events: List[Dict[str, Any]] = []
    cache = TieredCache(l2_backend=InMemoryTestL2())
    cache.on("cache:set", events.append)

    await cache.set("order-2", "value")

    assert len(events) == 1
    assert events[0]["event"] == "cache:set"
    assert events[0]["key"] == "order-2"


@pytest.mark.asyncio
async def test_stale_served_event_emitted() -> None:
    """Serving stale data during a factory failure should emit an event."""

    events: List[Dict[str, Any]] = []
    cache = TieredCache(l2_backend=InMemoryTestL2(), default_ttl=0.05, grace_period=1)
    cache.on("cache:stale-served", events.append)

    await cache.set("carrier", {"rate": 42}, ttl=0.05)
    await asyncio.sleep(0.1)

    async def failing_factory() -> str:
        raise RuntimeError("backend down")

    value = await cache.getOrSet("carrier", failing_factory, ttl=60)

    assert value == {"rate": 42}
    assert len(events) == 1
    assert events[0]["event"] == "cache:stale-served"
    assert events[0]["key"] == "carrier"


@pytest.mark.asyncio
async def test_listener_exception_does_not_propagate() -> None:
    """Listener failures should never break cache operations."""

    cache = TieredCache(l2_backend=InMemoryTestL2())

    def broken_listener(_: Dict[str, Any]) -> None:
        raise RuntimeError("listener failed")

    cache.on("cache:set", broken_listener)

    await cache.set("safe", "value")

    assert await cache.get("safe") == "value"
