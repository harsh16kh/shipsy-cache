"""In-process Redis simulation for demos and integration-style tests.

``FakeRedisL2`` gives developers Redis-like behavior without running an
external Redis container. It differs from ``MemoryStubL2`` in one important
way: ``MemoryStubL2`` stores Python objects directly with no serialization,
which is ideal for very fast unit tests where zero overhead and exact object
identity matter. ``FakeRedisL2`` JSON-serializes values on write and
deserializes them on read, which catches non-serializable payloads and more
closely mirrors real Redis behavior.

Choose ``MemoryStubL2`` for lightweight unit tests and straightforward local
usage. Choose ``FakeRedisL2`` for demos, integration-style tests, and failure
mode exercises where simulated latency, a serialization boundary, and injected
connection failures provide more realistic behavior.
"""

from __future__ import annotations

import asyncio
import json
import random
import time
from typing import Any, Dict, Optional, Tuple

from shipsy_cache.backends.base import L2Backend


class FakeRedisL2(L2Backend):
    """Redis-like in-process backend with JSON serialization and diagnostics."""

    def __init__(
        self,
        namespace: str = "shipsy_cache",
        latency_ms: float = 0.0,
        failure_rate: float = 0.0,
    ) -> None:
        """Initialize the fake Redis backend.

        Args:
            namespace: Prefix applied to all stored keys.
            latency_ms: Artificial round-trip latency applied to operations.
            failure_rate: Probability between 0.0 and 1.0 of simulating
                connection failures on get, set, and delete.

        Raises:
            ValueError: If ``latency_ms`` or ``failure_rate`` are invalid.
        """

        if latency_ms < 0:
            raise ValueError("latency_ms must be non-negative.")
        if not 0.0 <= failure_rate <= 1.0:
            raise ValueError("failure_rate must be between 0.0 and 1.0.")

        self._namespace = namespace
        self._latency_ms = latency_ms
        self._failure_rate = failure_rate
        self._store: Dict[str, Tuple[bytes, Optional[float]]] = {}
        self._lock = asyncio.Lock()
        self._op_count = 0
        self._failure_count = 0

    async def get(self, key: str) -> Optional[Any]:
        """Return the cached value for ``key`` or ``None``.

        Args:
            key: Logical cache key supplied by the caller.

        Returns:
            Deserialized cached value, or ``None`` when missing/expired.

        Raises:
            ConnectionError: When failure simulation triggers.
        """

        self._op_count += 1
        self._maybe_fail("get")
        await self._apply_latency()

        prefixed_key = self._prefix(key)
        async with self._lock:
            entry = self._store.get(prefixed_key)
            if entry is None:
                return None

            raw_value, expire_at = entry
            if expire_at is not None and time.monotonic() >= expire_at:
                self._store.pop(prefixed_key, None)
                return None

            return json.loads(raw_value)

    async def set(self, key: str, value: Any, ttl_seconds: Optional[float] = None) -> None:
        """Store a JSON-serializable value under ``key``.

        Args:
            key: Logical cache key supplied by the caller.
            value: JSON-serializable value to store.
            ttl_seconds: Optional time to live in seconds.

        Raises:
            ConnectionError: When failure simulation triggers.
            TypeError: If ``value`` is not JSON serializable.
            ValueError: If JSON serialization fails.
        """

        self._op_count += 1
        self._maybe_fail("set")
        await self._apply_latency()

        payload = json.dumps(value).encode("utf-8")
        expire_at = time.monotonic() + ttl_seconds if ttl_seconds else None
        async with self._lock:
            self._store[self._prefix(key)] = (payload, expire_at)

    async def delete(self, key: str) -> None:
        """Delete ``key`` if present.

        Args:
            key: Logical cache key supplied by the caller.

        Raises:
            ConnectionError: When failure simulation triggers.
        """

        self._op_count += 1
        self._maybe_fail("delete")
        await self._apply_latency()

        async with self._lock:
            self._store.pop(self._prefix(key), None)

    async def clear(self) -> None:
        """Delete all entries for the configured namespace."""

        await self._apply_latency()
        namespace_prefix = f"{self._namespace}:"
        async with self._lock:
            keys_to_delete = [key for key in self._store if key.startswith(namespace_prefix)]
            for key in keys_to_delete:
                self._store.pop(key, None)

    async def ping(self) -> bool:
        """Return ``True`` because the in-process simulator is reachable."""

        return True

    def diagnostics(self) -> Dict[str, Any]:
        """Return backend diagnostics for demos and tests."""

        now = time.monotonic()
        total_keys = len(self._store)
        live_keys = sum(
            1
            for _, expire_at in self._store.values()
            if expire_at is None or now < expire_at
        )
        return {
            "namespace": self._namespace,
            "total_keys": total_keys,
            "live_keys": live_keys,
            "expired_pending_eviction": total_keys - live_keys,
            "total_operations": self._op_count,
            "simulated_failures": self._failure_count,
        }

    async def _apply_latency(self) -> None:
        """Sleep to simulate network latency when configured."""

        if self._latency_ms > 0:
            await asyncio.sleep(self._latency_ms / 1000.0)

    def _maybe_fail(self, operation: str) -> None:
        """Raise a simulated connection failure when configured."""

        if self._failure_rate > 0 and random.random() < self._failure_rate:
            self._failure_count += 1
            raise ConnectionError(
                f"FakeRedisL2: simulated connection failure on {operation}",
            )

    def _prefix(self, key: str) -> str:
        """Return the internal prefixed storage key."""

        return f"{self._namespace}:{key}"
