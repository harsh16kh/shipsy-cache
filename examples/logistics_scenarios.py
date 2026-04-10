"""Practical usage patterns for Shipsy backend services.

Each function demonstrates a real caching pattern that maps to
Shipsy's logistics domain. No external dependencies required.

Run: python examples/logistics_scenarios.py
"""

from __future__ import annotations

import asyncio
import random
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from shipsy_cache import FakeRedisL2, FactoryError, TieredCache


CARRIERS: Dict[str, Dict[str, float]] = {
    "delhivery": {"base_rate": 45.0, "per_kg": 12.5},
    "bluedart": {"base_rate": 65.0, "per_kg": 18.0},
    "dtdc": {"base_rate": 38.0, "per_kg": 10.0},
    "ecom_express": {"base_rate": 42.0, "per_kg": 11.5},
    "xpressbees": {"base_rate": 40.0, "per_kg": 11.0},
    "shadowfax": {"base_rate": 35.0, "per_kg": 9.5},
}


async def fetch_rate(carrier: str, origin: str, destination: str, weight_kg: float) -> Dict[str, Any]:
    """Simulate carrier pricing APIs."""

    await asyncio.sleep(random.uniform(0.15, 0.30))
    carrier_data = CARRIERS[carrier]
    total = carrier_data["base_rate"] + (carrier_data["per_kg"] * weight_kg)
    return {
        "carrier": carrier,
        "origin": origin,
        "destination": destination,
        "weight_kg": weight_kg,
        "amount": round(total, 2),
        "fetched_at": time.time(),
    }


async def fetch_tracking(awb: str) -> Dict[str, Any]:
    """Simulate a shipment tracking API."""

    await asyncio.sleep(random.uniform(0.08, 0.15))
    return {
        "awb": awb,
        "status": random.choice(["manifested", "in_transit", "out_for_delivery", "delivered"]),
        "updated_at": time.time(),
    }


async def fetch_serviceability(pincode: str) -> Dict[str, Any]:
    """Simulate serviceability checks."""

    await asyncio.sleep(random.uniform(0.05, 0.12))
    carriers = list(CARRIERS.keys())[: max(2, (int(pincode[-1]) % len(CARRIERS)) + 1)]
    return {
        "pincode": pincode,
        "serviceable": True,
        "available_carriers": carriers,
        "checked_at": time.time(),
    }


async def fetch_merchant_config(merchant_id: str) -> Dict[str, Any]:
    """Simulate a slower merchant config service."""

    await asyncio.sleep(random.uniform(0.20, 0.35))
    return {
        "merchant_id": merchant_id,
        "delivery_sla_hours": 48,
        "rto_window_days": 7,
        "preferred_carriers": ["delhivery", "xpressbees", "shadowfax"],
        "auto_allocate": True,
        "updated_at": time.time(),
    }


async def rate_shopping_example() -> None:
    """Cache carrier rates during order creation to avoid hitting
    carrier APIs on every checkout."""

    print("\n=== Rate Shopping Example ===")
    cache = TieredCache(
        l2_backend=FakeRedisL2(namespace="rates-l2", latency_ms=5),
        namespace="rates",
        default_ttl="15m",
        grace_period="2m",
    )

    async def get_rate(carrier: str) -> Dict[str, Any]:
        return await cache.getOrSet(
            f"{carrier}:DEL:BLR:2.5",
            lambda: fetch_rate(carrier, "DEL", "BLR", 2.5),
            ttl="15m",
        )

    start = time.perf_counter()
    first_rates = await asyncio.gather(*(get_rate(carrier) for carrier in CARRIERS))
    first_elapsed = time.perf_counter() - start
    cheapest = sorted(first_rates, key=lambda rate: rate["amount"])[0]
    print(f"Cold fetch completed in {first_elapsed * 1000:.2f} ms")
    print(f"Cheapest carrier: {cheapest['carrier']} @ ₹{cheapest['amount']:.2f}")

    start = time.perf_counter()
    second_rates = await asyncio.gather(*(get_rate(carrier) for carrier in CARRIERS))
    second_elapsed = time.perf_counter() - start
    print(f"Warm fetch completed in {second_elapsed * 1000:.2f} ms")
    print(f"Second request returned {len(second_rates)} cached rates")


async def tracking_page_example() -> None:
    """Handle high-traffic tracking pages where thousands of customers
    check the same AWB simultaneously."""

    print("\n=== Tracking Page Example ===")
    cache = TieredCache(
        l2_backend=FakeRedisL2(namespace="tracking-l2", latency_ms=5),
        namespace="tracking",
        default_ttl="30s",
        grace_period="30s",
    )
    call_count = 0

    async def factory() -> Dict[str, Any]:
        nonlocal call_count
        call_count += 1
        return await fetch_tracking("AWB-DEL-78234")

    results = await asyncio.gather(*(cache.getOrSet("AWB-DEL-78234", factory, ttl="30s") for _ in range(100)))
    print(f"Factory call count: {call_count}")
    print(f"Concurrent requests served: {len(results)}")
    print(f"All payloads identical: {len({repr(item) for item in results}) == 1}")


async def serviceability_cache_example() -> None:
    """Cache pincode serviceability checks — these rarely change but
    are checked on every order."""

    print("\n=== Serviceability Cache Example ===")
    cache = TieredCache(
        l2_backend=FakeRedisL2(namespace="serviceability-l2", latency_ms=5),
        namespace="serviceability",
        default_ttl="6h",
        grace_period="10m",
    )
    call_count = 0

    async def factory() -> Dict[str, Any]:
        nonlocal call_count
        call_count += 1
        return await fetch_serviceability("560034")

    for _ in range(1000):
        await cache.getOrSet("560034", factory, ttl="6h")

    print(f"Serviceability factory call count: {call_count}")
    print(f"Cache stats: {cache.stats()}")


async def graceful_degradation_example() -> None:
    """When a carrier API goes down, serve last-known rates rather than
    failing the order creation flow."""

    print("\n=== Graceful Degradation Example ===")
    cache = TieredCache(
        l2_backend=FakeRedisL2(namespace="grace-l2", latency_ms=5),
        namespace="rates",
        default_ttl="10m",
        grace_period="30s",
    )
    key = "bluedart:DEL:BLR:2.0"

    warm_value = await cache.getOrSet(key, lambda: fetch_rate("bluedart", "DEL", "BLR", 2.0), ttl=0.5)
    print(f"Cached value: {warm_value}")
    print("Sleeping past TTL but within grace period...")
    await asyncio.sleep(0.6)

    async def failing_factory() -> Dict[str, Any]:
        await asyncio.sleep(0.05)
        raise ConnectionError("Carrier API unavailable")

    stale_value = await cache.getOrSet(key, failing_factory, ttl="15m")
    print(f"Returned stale value after upstream failure: {stale_value}")


async def multi_namespace_example() -> None:
    """Different services sharing the same Redis should have isolated caches."""

    print("\n=== Multi-Namespace Example ===")
    shared_l2 = FakeRedisL2(namespace="shared-l2", latency_ms=5)
    rate_cache = TieredCache(l2_backend=shared_l2, namespace="rates", default_ttl="10m", grace_period="1m")
    tracking_cache = TieredCache(
        l2_backend=shared_l2,
        namespace="tracking",
        default_ttl="30s",
        grace_period="30s",
    )

    await rate_cache.set("key:123", {"type": "rate", "amount": 120.5}, ttl="10m")
    await tracking_cache.set("key:123", {"type": "tracking", "status": "in_transit"}, ttl="30s")

    print(f"Rate cache value: {await rate_cache.get('key:123')}")
    print(f"Tracking cache value: {await tracking_cache.get('key:123')}")
    print(f"Shared L2 diagnostics: {shared_l2.diagnostics()}")


async def main() -> None:
    """Run all practical logistics examples sequentially."""

    await rate_shopping_example()
    await tracking_page_example()
    await serviceability_cache_example()
    await graceful_degradation_example()
    await multi_namespace_example()


if __name__ == "__main__":
    asyncio.run(main())
