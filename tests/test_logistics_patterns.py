"""Domain-specific tests for logistics-oriented cache access patterns.

These tests complement the generic cache suite by focusing on FakeRedisL2
behavior and logistics workflows that exercise serialization, namespace
isolation, hydration, and graceful degradation.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime
from typing import Any, Dict, List

import pytest

from shipsy_cache import FactoryError, FakeRedisL2, TieredCache


@pytest.mark.asyncio
async def test_fake_redis_json_serialization_boundary() -> None:
    """FakeRedisL2 must reject non-JSON-serializable values just like real Redis."""

    l2 = FakeRedisL2(namespace="serialization")

    with pytest.raises(TypeError):
        await l2.set("key", {"timestamp": datetime.now()}, ttl_seconds=30)

    payload = {"awb": "AWB-DEL-1001", "status": "in_transit", "attempts": [1, 2]}
    await l2.set("key", payload, ttl_seconds=30)
    returned = await l2.get("key")

    assert returned == payload
    assert returned is not payload


@pytest.mark.asyncio
async def test_fake_redis_latency_simulation() -> None:
    """Artificial latency should be measurable — proves the simulation is real."""

    l2 = FakeRedisL2(namespace="latency", latency_ms=100)

    start = time.perf_counter()
    await l2.get("missing")
    elapsed = time.perf_counter() - start

    assert elapsed >= 0.08


@pytest.mark.asyncio
async def test_fake_redis_failure_simulation() -> None:
    """Simulated failures should raise ConnectionError for resilience testing."""

    l2 = FakeRedisL2(namespace="failures", failure_rate=1.0)

    with pytest.raises(ConnectionError):
        await l2.get("key")
    with pytest.raises(ConnectionError):
        await l2.set("key", {"ok": True}, ttl_seconds=10)

    diagnostics = l2.diagnostics()
    assert diagnostics["simulated_failures"] >= 2


@pytest.mark.asyncio
async def test_fake_redis_namespace_isolation() -> None:
    """Two isolated FakeRedis namespaces should never leak values across logical domains."""

    l2_a = FakeRedisL2(namespace="rates")
    l2_b = FakeRedisL2(namespace="tracking")

    await l2_a.set("key:1", {"domain": "rates"}, ttl_seconds=60)
    await l2_b.set("key:1", {"domain": "tracking"}, ttl_seconds=60)

    assert await l2_a.get("key:1") == {"domain": "rates"}
    assert await l2_b.get("key:1") == {"domain": "tracking"}
    assert await l2_a.get("tracking:key:1") is None
    assert await l2_b.get("rates:key:1") is None


@pytest.mark.asyncio
async def test_stale_rate_served_during_carrier_outage() -> None:
    """When a carrier API goes down, the grace period should serve the last known rate."""

    l2 = FakeRedisL2(namespace="carrier-rates")
    cache = TieredCache(l2_backend=l2, namespace="rates", default_ttl="15m", grace_period="30s")
    original = {"carrier": "bluedart", "amount": 110.5, "currency": "INR"}

    await cache.set("bluedart:DEL:BLR", original, ttl=0.5)
    await asyncio.sleep(0.6)

    async def failing_factory() -> Dict[str, Any]:
        raise ConnectionError("Carrier outage")

    returned = await cache.getOrSet("bluedart:DEL:BLR", failing_factory, ttl="15m")

    assert returned == original


@pytest.mark.asyncio
async def test_no_stale_without_grace_period() -> None:
    """Without a grace period, expired keys with failing factories must raise."""

    l2 = FakeRedisL2(namespace="carrier-rates-no-grace")
    cache = TieredCache(l2_backend=l2, namespace="rates", default_ttl="15m", grace_period=0)

    await cache.set("bluedart:DEL:BLR", {"carrier": "bluedart", "amount": 110.5}, ttl=0.5)
    await asyncio.sleep(0.6)

    async def failing_factory() -> Dict[str, Any]:
        raise ConnectionError("Carrier outage")

    with pytest.raises(FactoryError):
        await cache.getOrSet("bluedart:DEL:BLR", failing_factory, ttl="15m")


@pytest.mark.asyncio
async def test_tiered_cache_namespace_isolation_shared_l2() -> None:
    """Multiple services sharing the same Redis must have fully isolated key namespaces."""

    l2 = FakeRedisL2(namespace="shared-redis")
    rate_cache = TieredCache(l2_backend=l2, namespace="rates", default_ttl="15m", grace_period="1m")
    tracking_cache = TieredCache(l2_backend=l2, namespace="tracking", default_ttl="30s", grace_period="30s")

    await rate_cache.set("key:123", {"service": "rates", "amount": 90.0}, ttl="15m")
    await tracking_cache.set("key:123", {"service": "tracking", "status": "at_hub"}, ttl="30s")

    assert await rate_cache.get("key:123") == {"service": "rates", "amount": 90.0}
    assert await tracking_cache.get("key:123") == {"service": "tracking", "status": "at_hub"}


@pytest.mark.asyncio
async def test_l2_hydration_populates_l1() -> None:
    """A value written by another instance into L2 should hydrate local L1 on first read."""

    l2 = FakeRedisL2(namespace="hydration")
    cache = TieredCache(l2_backend=l2, namespace="tracking", default_ttl="5m", grace_period="30s")
    payload = {"awb": "AWB-BLR-2002", "status": "out_for_delivery"}
    before = cache.stats()["l1"]["size"]

    await l2.set(cache._namespaced_key("AWB-BLR-2002"), payload, ttl_seconds=60)
    returned = await cache.get("AWB-BLR-2002")
    after = cache.stats()["l1"]["size"]

    assert returned == payload
    assert after > before


@pytest.mark.asyncio
async def test_rate_shopping_concurrent_with_fake_redis() -> None:
    """Concurrent rate shopping should still stampede-protect through the serialized FakeRedis path."""

    l2 = FakeRedisL2(namespace="rate-shopping", latency_ms=10)
    cache = TieredCache(l2_backend=l2, namespace="rates", default_ttl="15m", grace_period="2m")
    call_count = 0

    async def factory() -> Dict[str, Any]:
        nonlocal call_count
        call_count += 1
        await asyncio.sleep(0.05)
        return {"carrier": "delhivery", "route": "DEL-BLR", "amount": 76.25}

    results = await asyncio.gather(
        *(cache.getOrSet("delhivery:DEL:BLR", factory, ttl="15m") for _ in range(20)),
    )

    assert call_count == 1
    assert len({repr(result) for result in results}) == 1
    assert all(result == {"carrier": "delhivery", "route": "DEL-BLR", "amount": 76.25} for result in results)


@pytest.mark.asyncio
async def test_high_read_serviceability_pattern() -> None:
    """Serviceability data should handle a heavy read pattern with fast in-memory responses."""

    l2 = FakeRedisL2(namespace="serviceability")
    cache = TieredCache(l2_backend=l2, namespace="serviceability", default_ttl="6h", grace_period="5m")
    payload = {
        "pincode": "560034",
        "serviceable": True,
        "available_carriers": ["delhivery", "xpressbees", "ecom_express"],
    }

    await cache.set("560034", payload, ttl=21600)

    start = time.perf_counter()
    results: List[Any] = [await cache.get("560034") for _ in range(500)]
    elapsed = time.perf_counter() - start

    assert all(result == payload for result in results)
    assert elapsed < 0.1
