"""Logistics-specific tests for the Shipsy cache library."""

from __future__ import annotations

import asyncio
import time
from datetime import datetime
from typing import Any, Dict, List

import pytest

from shipsy_cache import FactoryError, FakeRedisL2, TieredCache


@pytest.mark.asyncio
async def test_rate_shopping_concurrent_stampede() -> None:
    """Concurrent rate shopping for one carrier should trigger exactly one upstream call."""

    l2 = FakeRedisL2(namespace="rates-l2")
    cache = TieredCache(l2_backend=l2, namespace="rates", default_ttl="15m", grace_period="2m")
    call_count = 0

    async def factory() -> Dict[str, Any]:
        nonlocal call_count
        call_count += 1
        await asyncio.sleep(0.1)
        return {"carrier": "delhivery", "amount": 76.25, "currency": "INR"}

    results = await asyncio.gather(*(cache.getOrSet("delhivery:DEL:BLR:2.5", factory, ttl="15m") for _ in range(20)))

    assert call_count == 1
    assert len({repr(result) for result in results}) == 1
    assert all(result["carrier"] == "delhivery" and result["amount"] == 76.25 for result in results)


@pytest.mark.asyncio
async def test_tracking_short_ttl_lifecycle() -> None:
    """Tracking data with short TTL should disappear after expiry."""

    l2 = FakeRedisL2(namespace="tracking-l2")
    cache = TieredCache(l2_backend=l2, namespace="tracking", default_ttl="30s", grace_period="5s")
    payload = {"awb": "AWB-DEL-78234", "status": "in_transit"}

    await cache.set("AWB-DEL-78234", payload, ttl=0.5)

    assert await cache.get("AWB-DEL-78234") == payload
    await asyncio.sleep(0.6)
    assert await cache.get("AWB-DEL-78234") is None


@pytest.mark.asyncio
async def test_stale_rate_served_during_carrier_outage() -> None:
    """Expired carrier rates should be served from stale data during a temporary outage."""

    l2 = FakeRedisL2(namespace="grace-l2")
    cache = TieredCache(l2_backend=l2, namespace="rates", default_ttl="10m", grace_period="30s")
    payload = {"carrier": "bluedart", "amount": 92.0}

    await cache.set("bluedart:DEL:BLR", payload, ttl=0.5)
    await asyncio.sleep(0.6)

    async def failing_factory() -> Dict[str, Any]:
        raise ConnectionError("Carrier outage")

    stale = await cache.getOrSet("bluedart:DEL:BLR", failing_factory, ttl="15m")

    assert stale == payload


@pytest.mark.asyncio
async def test_no_stale_without_grace_period() -> None:
    """Without a grace period, an expired rate should raise instead of serving stale data."""

    l2 = FakeRedisL2(namespace="no-grace-l2")
    cache = TieredCache(l2_backend=l2, namespace="rates", default_ttl="10m", grace_period=0)

    await cache.set("bluedart:DEL:BLR", {"carrier": "bluedart", "amount": 92.0}, ttl=0.5)
    await asyncio.sleep(0.6)

    async def failing_factory() -> Dict[str, Any]:
        raise ConnectionError("Carrier outage")

    with pytest.raises(FactoryError):
        await cache.getOrSet("bluedart:DEL:BLR", failing_factory, ttl="15m")


@pytest.mark.asyncio
async def test_namespace_isolation_on_shared_l2() -> None:
    """Two services sharing the same FakeRedis backend should stay logically isolated by namespace."""

    l2 = FakeRedisL2(namespace="shared-l2")
    cache_a = TieredCache(l2_backend=l2, namespace="rates", default_ttl="10m", grace_period="1m")
    cache_b = TieredCache(l2_backend=l2, namespace="tracking", default_ttl="10m", grace_period="1m")

    await cache_a.set("key:123", {"service": "rates"}, ttl="10m")
    await cache_b.set("key:123", {"service": "tracking"}, ttl="10m")

    assert await cache_a.get("key:123") == {"service": "rates"}
    assert await cache_b.get("key:123") == {"service": "tracking"}


@pytest.mark.asyncio
async def test_l2_json_serialization_catches_non_serializable() -> None:
    """The fake Redis backend should reject values that cannot cross a JSON serialization boundary."""

    l2 = FakeRedisL2(namespace="serialization-l2")

    with pytest.raises(TypeError):
        await l2.set("bad:datetime", {"value": datetime.utcnow()}, ttl_seconds=60)


@pytest.mark.asyncio
async def test_fake_redis_latency_simulation() -> None:
    """Configured backend latency should materially slow down read operations."""

    l2 = FakeRedisL2(namespace="latency-l2", latency_ms=50)

    start = time.perf_counter()
    await l2.get("missing")
    elapsed = time.perf_counter() - start

    assert elapsed >= 0.04


@pytest.mark.asyncio
async def test_fake_redis_failure_simulation() -> None:
    """The fake Redis backend should simulate connection failures when configured to do so."""

    l2 = FakeRedisL2(namespace="failure-l2", failure_rate=1.0)

    with pytest.raises(ConnectionError):
        await l2.get("key")
    with pytest.raises(ConnectionError):
        await l2.set("key", {"ok": True}, ttl_seconds=60)


@pytest.mark.asyncio
async def test_serviceability_high_read_low_write() -> None:
    """High read volume for serviceability checks should keep reusing one cached value."""

    l2 = FakeRedisL2(namespace="svc-l2")
    cache = TieredCache(l2_backend=l2, namespace="serviceability", default_ttl=21600, grace_period=60)
    call_count = 0

    async def factory() -> Dict[str, Any]:
        nonlocal call_count
        call_count += 1
        return {
            "pincode": "560034",
            "serviceable": True,
            "available_carriers": ["delhivery", "xpressbees"],
        }

    results: List[Dict[str, Any]] = []
    for _ in range(500):
        results.append(await cache.getOrSet("560034", factory, ttl=21600))

    assert call_count == 1
    assert len({repr(result) for result in results}) == 1


@pytest.mark.asyncio
async def test_l2_hydration_populates_l1() -> None:
    """A value written directly to shared L2 should hydrate local L1 on the first cache read."""

    l2 = FakeRedisL2(namespace="hydration-l2")
    cache = TieredCache(l2_backend=l2, namespace="tracking", default_ttl="5m", grace_period="30s")
    key = "AWB-HYD-55678"
    payload = {"awb": key, "status": "out_for_delivery"}
    before = cache.stats()["l1"]["size"]

    await l2.set(cache._namespaced_key(key), payload, ttl_seconds=60)
    value = await cache.get(key)
    after = cache.stats()["l1"]["size"]

    assert value == payload
    assert after > before
