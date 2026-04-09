"""Integration tests against a real Redis instance."""

from __future__ import annotations

import asyncio
import os
import time
import uuid

import pytest

from shipsy_cache import L2UnavailableError, RedisL2, TieredCache

pytestmark = pytest.mark.skipif(
    not os.getenv("REDIS_HOST"),
    reason="REDIS_HOST not set — skipping Redis integration tests",
)


@pytest.fixture
async def redis_cache() -> TieredCache:
    """Create a Redis-backed cache or skip if Redis is unavailable."""

    namespace = f"itest-{uuid.uuid4().hex[:8]}"
    backend = RedisL2(namespace="shipsy_integration")
    cache = TieredCache(l2_backend=backend, namespace=namespace)
    try:
        await backend.ping()
    except L2UnavailableError as exc:
        pytest.skip(f"Redis unavailable: {exc}")

    await cache.clear()
    yield cache
    await cache.clear()


@pytest.mark.asyncio
async def test_redis_set_get_roundtrip(redis_cache: TieredCache) -> None:
    """Redis-backed cache should support a basic roundtrip."""

    await redis_cache.set("roundtrip", {"status": "ok"}, ttl=5)

    assert await redis_cache.get("roundtrip") == {"status": "ok"}


@pytest.mark.asyncio
async def test_redis_ttl_expiry(redis_cache: TieredCache) -> None:
    """Redis-backed entries should expire based on TTL."""

    await redis_cache.set("expiring", "value", ttl=1)
    await asyncio.sleep(1.2)

    assert await redis_cache.get("expiring") is None


@pytest.mark.asyncio
async def test_redis_namespace_isolation() -> None:
    """Namespaces should isolate identical logical keys in Redis."""

    backend = RedisL2(namespace="shipsy_integration")
    cache_a = TieredCache(l2_backend=backend, namespace=f"ns-a-{uuid.uuid4().hex[:6]}")
    cache_b = TieredCache(l2_backend=backend, namespace=f"ns-b-{uuid.uuid4().hex[:6]}")
    try:
        await backend.ping()
    except L2UnavailableError as exc:
        pytest.skip(f"Redis unavailable: {exc}")

    await cache_a.set("same", "a", ttl=5)
    await cache_b.set("same", "b", ttl=5)

    assert await cache_a.get("same") == "a"
    assert await cache_b.get("same") == "b"

    await cache_a.clear()
    await cache_b.clear()


@pytest.mark.asyncio
async def test_redis_ping() -> None:
    """Redis ping should return ``True`` for a healthy instance."""

    backend = RedisL2(namespace="shipsy_integration")
    try:
        assert await backend.ping() is True
    except L2UnavailableError as exc:
        pytest.skip(f"Redis unavailable: {exc}")
