"""Concurrency tests for stampede protection."""

from __future__ import annotations

import asyncio

import pytest

from shipsy_cache import TieredCache
from tests.support import InMemoryTestL2


@pytest.mark.asyncio
async def test_stampede_factory_called_exactly_once() -> None:
    """Twenty concurrent callers should trigger the factory only once."""

    call_count = 0

    async def slow_factory() -> str:
        nonlocal call_count
        call_count += 1
        await asyncio.sleep(0.1)
        return "result_value"

    cache = TieredCache(l2_backend=InMemoryTestL2())
    tasks = [cache.getOrSet("hot_key", slow_factory, ttl=60) for _ in range(20)]
    results = await asyncio.gather(*tasks)

    assert call_count == 1, f"Factory called {call_count} times, expected 1"
    assert all(result == "result_value" for result in results)


@pytest.mark.asyncio
async def test_stampede_different_keys_independent() -> None:
    """Different keys should maintain separate inflight coordination."""

    key_a_calls = 0
    key_b_calls = 0

    async def factory_a() -> str:
        nonlocal key_a_calls
        key_a_calls += 1
        await asyncio.sleep(0.05)
        return "a"

    async def factory_b() -> str:
        nonlocal key_b_calls
        key_b_calls += 1
        await asyncio.sleep(0.05)
        return "b"

    cache = TieredCache(l2_backend=InMemoryTestL2())
    results = await asyncio.gather(
        *(cache.getOrSet("key-a", factory_a, ttl=60) for _ in range(10)),
        *(cache.getOrSet("key-b", factory_b, ttl=60) for _ in range(10)),
    )

    assert key_a_calls == 1
    assert key_b_calls == 1
    assert results.count("a") == 10
    assert results.count("b") == 10


@pytest.mark.asyncio
async def test_stampede_after_cache_populated_no_factory_call() -> None:
    """Warm keys should bypass stampede logic and skip the factory."""

    call_count = 0

    async def factory() -> str:
        nonlocal call_count
        call_count += 1
        return "new-value"

    cache = TieredCache(l2_backend=InMemoryTestL2())
    await cache.set("ready", "existing", ttl=60)

    results = await asyncio.gather(*(cache.getOrSet("ready", factory, ttl=60) for _ in range(10)))

    assert call_count == 0
    assert all(result == "existing" for result in results)


@pytest.mark.asyncio
async def test_concurrent_factory_failure_propagates_same_failure_outcome() -> None:
    """Concurrent callers should share one factory failure for the same cold key."""

    call_count = 0

    async def failing_factory() -> str:
        nonlocal call_count
        call_count += 1
        await asyncio.sleep(0.05)
        raise RuntimeError("upstream exploded")

    cache = TieredCache(l2_backend=InMemoryTestL2())
    results = await asyncio.gather(
        *(cache.getOrSet("failing-key", failing_factory, ttl=60) for _ in range(20)),
        return_exceptions=True,
    )

    assert call_count == 1
    assert all(isinstance(result, Exception) for result in results)
    assert all(type(result).__name__ == "FactoryError" for result in results)
    assert len({str(result) for result in results}) == 1


@pytest.mark.asyncio
async def test_concurrent_stale_fallback_returns_same_stale_value() -> None:
    """Concurrent callers should share a single stale fallback result within grace."""

    call_count = 0
    cache = TieredCache(l2_backend=InMemoryTestL2(), default_ttl=0.05, grace_period=1)
    await cache.set("stale-key", {"value": "old"}, ttl=0.05)
    await asyncio.sleep(0.1)

    async def failing_factory() -> dict[str, str]:
        nonlocal call_count
        call_count += 1
        await asyncio.sleep(0.05)
        raise RuntimeError("carrier outage")

    results = await asyncio.gather(
        *(cache.getOrSet("stale-key", failing_factory, ttl=60) for _ in range(20)),
    )

    assert call_count == 1
    assert all(result == {"value": "old"} for result in results)


@pytest.mark.asyncio
async def test_inflight_factory_can_repopulate_after_invalidate() -> None:
    """Invalidate does not cancel an in-flight leader; the completed result can repopulate the key."""

    cache = TieredCache(l2_backend=InMemoryTestL2())
    factory_started = asyncio.Event()
    release_factory = asyncio.Event()

    async def factory() -> str:
        factory_started.set()
        await release_factory.wait()
        return "rebuilt"

    task = asyncio.create_task(cache.getOrSet("invalidate-race", factory, ttl=60))
    await factory_started.wait()
    await cache.invalidate("invalidate-race")
    release_factory.set()

    assert await task == "rebuilt"
    assert await cache.get("invalidate-race") == "rebuilt"
