"""Focused tests for internal branches and adapters that impact coverage."""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Dict, List, Optional

import pytest

from shipsy_cache import CacheEventEmitter, FactoryError, L2UnavailableError, TieredCache
from shipsy_cache.l1.memory_store import MemoryStore
from shipsy_cache.l2.redis_store import RedisError, RedisL2
from tests.support import InMemoryTestL2


class MockRedisClient:
    """Small async Redis client test double."""

    def __init__(self) -> None:
        """Initialize storage and recorded calls."""

        self.storage: Dict[str, str] = {}
        self.last_set_call: Optional[tuple[str, str, int]] = None
        self.scan_calls = 0

    async def get(self, key: str) -> Optional[str]:
        """Return the stored raw value."""

        return self.storage.get(key)

    async def set(self, key: str, value: str, px: int) -> bool:
        """Record the write and store the raw payload."""

        self.last_set_call = (key, value, px)
        self.storage[key] = value
        return True

    async def delete(self, *keys: str) -> int:
        """Delete one or more keys."""

        deleted = 0
        for key in keys:
            if key in self.storage:
                deleted += 1
                self.storage.pop(key)
        return deleted

    async def scan(self, cursor: int, match: str, count: int) -> tuple[int, List[str]]:
        """Return a single matching page."""

        self.scan_calls += 1
        matching = [key for key in self.storage if key.startswith(match[:-1])]
        return 0, matching

    async def ping(self) -> bool:
        """Return a healthy ping response."""

        return True


class ErrorRedisClient:
    """Async Redis client test double that raises on every operation."""

    async def get(self, key: str) -> Optional[str]:
        raise RedisError("boom")

    async def set(self, key: str, value: str, px: int) -> bool:
        raise RedisError("boom")

    async def delete(self, *keys: str) -> int:
        raise RedisError("boom")

    async def scan(self, cursor: int, match: str, count: int) -> tuple[int, List[str]]:
        raise RedisError("boom")

    async def ping(self) -> bool:
        raise RedisError("boom")


@pytest.mark.asyncio
async def test_async_event_listener_runs_without_blocking() -> None:
    """Async listeners should be scheduled and complete successfully."""

    emitter = CacheEventEmitter()
    seen: List[Dict[str, Any]] = []
    completed = asyncio.Event()

    async def async_listener(payload: Dict[str, Any]) -> None:
        await asyncio.sleep(0)
        seen.append(payload)
        completed.set()

    emitter.on("cache:hit", async_listener)
    emitter.emit("cache:hit", {"event": "cache:hit", "key": "k", "timestamp": 1.0})
    await asyncio.wait_for(completed.wait(), timeout=1)

    assert seen == [{"event": "cache:hit", "key": "k", "timestamp": 1.0}]


def test_async_event_listener_without_running_loop_does_not_raise() -> None:
    """Dropping async listeners without a loop should not explode or leak warnings."""

    emitter = CacheEventEmitter()

    async def async_listener(payload: Dict[str, Any]) -> None:
        return None

    coroutine = async_listener({"event": "cache:hit", "key": "k", "timestamp": 1.0})
    emitter._schedule_async_listener("cache:hit", async_listener, coroutine)


def test_memory_store_enforces_max_size_and_supports_stale_reads() -> None:
    """MemoryStore should evict LRU entries and surface stale values."""

    store = MemoryStore(max_size=2)
    store.set("a", 1, ttl_seconds=60)
    store.set("b", 2, ttl_seconds=60)
    assert store.get("a") == 1

    store.set("c", 3, ttl_seconds=60)

    assert store.get("b") is None
    assert store.get("a") == 1
    assert store.get("c") == 3

    short_store = MemoryStore(max_size=1)
    short_store.set("stale", "value", ttl_seconds=0.01)
    time.sleep(0.02)
    assert short_store.get("stale") is None
    assert short_store.get_stale("stale") == "value"
    assert short_store._get_entry("stale") is not None
    short_store.delete("stale")
    assert short_store.get_stale("stale") is None
    short_store.clear()
    assert short_store.stats() == {"size": 0, "max_size": 1}


def test_memory_store_rejects_invalid_max_size() -> None:
    """MemoryStore should reject non-positive sizes."""

    with pytest.raises(ValueError):
        MemoryStore(max_size=0)


@pytest.mark.asyncio
async def test_redis_l2_methods_and_error_wrapping() -> None:
    """RedisL2 should namespace keys, serialize payloads, and wrap backend errors."""

    backend = RedisL2(namespace="unit")
    client = MockRedisClient()
    backend._client = client

    await backend.set("key", {"value": 7}, ttl_seconds=0.5)
    assert client.last_set_call == ("unit:key", json.dumps({"value": 7}), 500)

    assert await backend.get("key") == {"value": 7}
    assert backend._prefix("x") == "unit:x"
    assert await backend.ping() is True

    client.storage["unit:other"] = json.dumps({"extra": True})
    await backend.clear()
    assert client.scan_calls >= 1
    assert client.storage == {}

    await backend.set("delete-me", {"gone": True}, ttl_seconds=1)
    await backend.delete("delete-me")
    assert "unit:delete-me" not in client.storage

    backend._client = ErrorRedisClient()
    with pytest.raises(L2UnavailableError):
        await backend.get("key")
    with pytest.raises(L2UnavailableError):
        await backend.set("key", {"value": 1}, ttl_seconds=1)
    with pytest.raises(L2UnavailableError):
        await backend.delete("key")
    with pytest.raises(L2UnavailableError):
        await backend.clear()
    with pytest.raises(L2UnavailableError):
        await backend.ping()


@pytest.mark.asyncio
async def test_cache_internal_branches_are_exercised() -> None:
    """Exercise smaller internal branches that are hard to reach via public API alone."""

    cache = TieredCache(l2_backend=InMemoryTestL2())

    assert cache._get_stale_within_grace(cache._namespaced_key("missing")) is None
    cache._cleanup_inflight("missing")

    class WriteFailL2:
        async def get(self, key: str) -> Optional[Any]:
            return None

        async def set(self, key: str, value: Any, ttl_seconds: float) -> None:
            raise L2UnavailableError("write failure")

        async def delete(self, key: str) -> None:
            return None

        async def clear(self) -> None:
            return None

        async def ping(self) -> bool:
            return True

    failing_cache = TieredCache(l2_backend=WriteFailL2())

    with pytest.raises(L2UnavailableError):
        await failing_cache.set("k", "v", ttl=1)

    lock_key = cache._namespaced_key("inflight-error")
    cache._inflight[lock_key] = asyncio.Lock()
    cache._inflight_waiters[lock_key] = 1
    cache._inflight_results[lock_key] = (
        False,
        L2UnavailableError("leader failed"),
    )
    await cache._inflight[lock_key].acquire()

    async def release_lock() -> None:
        await asyncio.sleep(0.01)
        cache._inflight[lock_key].release()

    releaser = asyncio.create_task(release_lock())
    with pytest.raises(L2UnavailableError):
        await cache.getOrSet("inflight-error", lambda: _unexpected_factory(), ttl=1)
    await releaser

    missing_lock_key = cache._namespaced_key("inflight-missing")
    cache._inflight[missing_lock_key] = asyncio.Lock()
    cache._inflight_waiters[missing_lock_key] = 1
    await cache._inflight[missing_lock_key].acquire()

    async def release_missing_lock() -> None:
        await asyncio.sleep(0.01)
        cache._inflight[missing_lock_key].release()

    missing_releaser = asyncio.create_task(release_missing_lock())
    with pytest.raises(FactoryError):
        await cache.getOrSet("inflight-missing", lambda: _unexpected_factory(), ttl=1)
    await missing_releaser

    calls = 0

    async def factory() -> str:
        nonlocal calls
        calls += 1
        return "new"

    class DelayMissL2:
        def __init__(self) -> None:
            self.waiter = asyncio.Event()

        async def get(self, key: str) -> Optional[Any]:
            await self.waiter.wait()
            return None

        async def set(self, key: str, value: Any, ttl_seconds: float) -> None:
            return None

        async def delete(self, key: str) -> None:
            return None

        async def clear(self) -> None:
            return None

        async def ping(self) -> bool:
            return True

    delay_l2 = DelayMissL2()
    delay_cache = TieredCache(l2_backend=delay_l2)
    task = asyncio.create_task(delay_cache.getOrSet("double-check-hit", factory, ttl=1))
    await asyncio.sleep(0)
    delay_cache._l1.set(delay_cache._namespaced_key("double-check-hit"), "ready", 60)
    delay_l2.waiter.set()

    assert await task == "ready"
    assert calls == 0


async def _unexpected_factory() -> str:
    """Factory used in tests that should never execute."""

    raise AssertionError("Factory should not have been called.")
