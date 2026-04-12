"""Tests for TTL parsing and expiry behavior."""

from __future__ import annotations

import asyncio

import pytest

from shipsy_cache import TieredCache, parse_ttl
from tests.support import InMemoryTestL2


def test_parse_ttl_seconds_int() -> None:
    """Numeric TTL values should parse directly to float seconds."""

    assert parse_ttl(300) == 300.0


def test_parse_ttl_string_minutes() -> None:
    """Minute TTL strings should convert to seconds."""

    assert parse_ttl("30m") == 1800.0


def test_parse_ttl_string_hours() -> None:
    """Hour TTL strings should convert to seconds."""

    assert parse_ttl("2h") == 7200.0


def test_parse_ttl_invalid_raises() -> None:
    """Invalid TTL strings should raise ``ValueError``."""

    with pytest.raises(ValueError):
        parse_ttl("abc")


@pytest.mark.asyncio
async def test_expired_key_not_returned() -> None:
    """Expired entries should not be returned by cache reads."""

    cache = TieredCache(l2_backend=InMemoryTestL2(), default_ttl=0.05)
    await cache.set("expiring", "value", ttl=0.05)

    await asyncio.sleep(0.1)

    assert await cache.get("expiring") is None


@pytest.mark.asyncio
async def test_fresh_key_returned() -> None:
    """Fresh entries should be returned before their TTL elapses."""

    cache = TieredCache(l2_backend=InMemoryTestL2(), default_ttl=60)
    await cache.set("fresh", "value", ttl=60)

    assert await cache.get("fresh") == "value"


@pytest.mark.asyncio
async def test_ttl_applied_to_l1_and_l2() -> None:
    """The same TTL should be enforced across both tiers."""

    cache = TieredCache(l2_backend=InMemoryTestL2(), default_ttl=0.05)
    await cache.set("ttl-key", {"ok": True}, ttl=0.05)

    namespaced_key = cache._namespaced_key("ttl-key")
    assert cache._l1.get(namespaced_key) == {"ok": True}
    assert await cache._l2.get(namespaced_key) == {"ok": True}

    await asyncio.sleep(0.1)

    assert cache._l1.get(namespaced_key) is None
    assert await cache._l2.get(namespaced_key) is None


@pytest.mark.asyncio
async def test_l2_hydration_preserves_remaining_ttl() -> None:
    """Hydrating L1 from L2 should preserve the remaining L2 TTL, not reset it."""

    l2 = InMemoryTestL2()
    cache = TieredCache(l2_backend=l2, default_ttl=60)
    namespaced_key = cache._namespaced_key("hydrated")
    await l2.set(namespaced_key, {"value": "from-l2"}, ttl_seconds=0.2)

    await asyncio.sleep(0.1)
    assert await cache.get("hydrated") == {"value": "from-l2"}
    assert cache._l1.get(namespaced_key) == {"value": "from-l2"}

    await asyncio.sleep(0.13)
    assert await cache.get("hydrated") is None


@pytest.mark.asyncio
async def test_expired_l2_entries_are_not_returned_on_hydration() -> None:
    """Expired L2 entries should not be surfaced or reintroduced into L1."""

    l2 = InMemoryTestL2()
    cache = TieredCache(l2_backend=l2, default_ttl=60)
    namespaced_key = cache._namespaced_key("expired-l2-only")
    await l2.set(namespaced_key, {"value": "gone"}, ttl_seconds=0.05)

    await asyncio.sleep(0.1)
    assert await cache.get("expired-l2-only") is None
    assert cache._l1.get(namespaced_key) is None
