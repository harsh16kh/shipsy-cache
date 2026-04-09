"""Demonstrates basic TieredCache usage with MemoryStubL2 (no Redis needed).
Shows: getOrSet, TTL, invalidation, event listening.
Run: python examples/basic_usage.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any, Dict

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shipsy_cache import TieredCache


async def main() -> None:
    """Run the basic usage walkthrough."""

    cache = TieredCache(default_ttl=1, grace_period=2, namespace="basic-demo")

    def log_event(payload: Dict[str, Any]) -> None:
        print(f"EVENT {payload['event']}: key={payload['key']} tier={payload.get('tier', '-')}")

    for event_name in (
        "cache:hit",
        "cache:miss",
        "cache:set",
        "cache:stale-served",
        "cache:invalidate",
    ):
        cache.on(event_name, log_event)

    factory_calls = 0

    async def slow_database_lookup() -> Dict[str, Any]:
        nonlocal factory_calls
        factory_calls += 1
        print("Factory: fetching from the mock database...")
        await asyncio.sleep(0.2)
        return {"order_id": "ORD-1001", "status": "in_transit"}

    print("\nFirst getOrSet() call: cache miss, factory runs")
    first = await cache.getOrSet("order:1001", slow_database_lookup, ttl=1)
    print("Result:", first)
    print("Factory calls:", factory_calls)

    print("\nSecond getOrSet() call: cache hit, factory does not run")
    second = await cache.getOrSet("order:1001", slow_database_lookup, ttl=1)
    print("Result:", second)
    print("Factory calls:", factory_calls)

    print("\nSleeping past TTL...")
    await asyncio.sleep(1.1)
    print("After TTL expiry, get() returns:", await cache.get("order:1001"))

    print("\nRebuilding value after expiry")
    rebuilt = await cache.getOrSet("order:1001", slow_database_lookup, ttl=1)
    print("Result:", rebuilt)
    print("Factory calls:", factory_calls)

    print("\nInvalidating the key")
    await cache.invalidate("order:1001")
    print("After invalidate, get() returns:", await cache.get("order:1001"))


if __name__ == "__main__":
    asyncio.run(main())
