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
