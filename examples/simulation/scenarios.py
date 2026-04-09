"""Real cache behavior scenarios for the simulation demo."""

from __future__ import annotations

import asyncio
from typing import Any, List

from logger import log
from mock_services import failing_service, fetch_rate
from shipsy_cache import TieredCache


async def cold_start_scenario(cache: TieredCache) -> None:
    """Demonstrate a cold key being computed and cached."""

    key = "simulation:cold-start:blr-del"
    await cache.invalidate(key)
    log("SCENARIO", f"Requesting cold key '{key}' with getOrSet().")
    result = await cache.getOrSet(key, lambda: fetch_rate("BLR", "DEL"), ttl="4s")
    log("RESULT", f"Cold start result: {result}")


async def cache_hit_scenario(cache: TieredCache) -> None:
    """Demonstrate a miss followed by a direct cache hit."""

    key = "simulation:cache-hit:maa-hyd"
    await cache.invalidate(key)
    factory_calls = 0

    async def rate_factory() -> Any:
        nonlocal factory_calls
        factory_calls += 1
        return await fetch_rate("MAA", "HYD")

    first = await cache.getOrSet(key, rate_factory, ttl="4s")
    second = await cache.getOrSet(key, rate_factory, ttl="4s")
    log("RESULT", f"First request result: {first}")
    log("RESULT", f"Second request result: {second}")
    log("RESULT", f"Factory executed {factory_calls} time(s).")


async def l2_hydration_scenario(cache: TieredCache) -> None:
    """Demonstrate L2 serving a value and repopulating L1."""

    key = "simulation:l2-hydration:bom-pnq"
    namespaced_key = cache._namespaced_key(key)
    value = await fetch_rate("BOM", "PNQ")

    cache._l1.delete(namespaced_key)
    await cache._l2.set(namespaced_key, value, ttl_seconds=5)

    hydrated = await cache.get(key)
    l1_value = cache._l1.get(namespaced_key)
    log("RESULT", f"L2 hydration returned: {hydrated}")
    log("RESULT", f"L1 after hydration: {l1_value}")


async def stampede_scenario(cache: TieredCache) -> None:
    """Demonstrate that concurrent callers execute the factory only once."""

    key = "simulation:stampede:hot-route"
    await cache.invalidate(key)
    factory_calls = 0

    async def expensive_factory() -> Any:
        nonlocal factory_calls
        factory_calls += 1
        log("SERVICE", f"Factory executing for '{key}' (call {factory_calls}).")
        await asyncio.sleep(0.5)
        return await fetch_rate("CCU", "BLR")

    results: List[Any] = await asyncio.gather(
        *(cache.getOrSet(key, expensive_factory, ttl="5s") for _ in range(20)),
    )

    if factory_calls != 1:
        raise AssertionError(f"Factory executed {factory_calls} times, expected 1.")
    if len({repr(result) for result in results}) != 1:
        raise AssertionError("Stampede results differed across concurrent callers.")

    log("RESULT", f"Stampede returned {len(results)} identical results.")
    log("RESULT", f"Factory executed {factory_calls} time(s).")


async def ttl_expiry_scenario(cache: TieredCache) -> None:
    """Demonstrate TTL expiry using real cache reads."""

    key = "simulation:ttl-expiry:del-jai"
    await cache.invalidate(key)
    value = await fetch_rate("DEL", "JAI")

    await cache.set(key, value, ttl="2s")
    immediate = await cache.get(key)
    log("RESULT", f"Immediate fetch after set: {immediate}")

    log("SCENARIO", "Sleeping 3 seconds to let the TTL expire.")
    await asyncio.sleep(3)
    expired = await cache.get(key)
    log("RESULT", f"Fetch after expiry: {expired}")


async def graceful_degradation_scenario(cache: TieredCache) -> None:
    """Demonstrate stale serving when the upstream factory fails."""

    key = "simulation:graceful-degradation:hyd-pat"
    await cache.invalidate(key)

    warm_value = await cache.getOrSet(key, lambda: fetch_rate("HYD", "PAT"), ttl="2s")
    log("RESULT", f"Warm value cached: {warm_value}")

    log("SCENARIO", "Sleeping 2.5 seconds so the cached value becomes stale but remains within grace.")
    await asyncio.sleep(2.5)

    degraded = await cache.getOrSet(key, failing_service, ttl="2s")
    log("RESULT", f"Graceful degradation returned stale value: {degraded}")
