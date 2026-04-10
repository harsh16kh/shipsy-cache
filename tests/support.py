"""Test-only backend helpers for unit tests.

These helpers keep the public library surface focused on Redis while still
allowing the unit suite to exercise cache behavior without requiring a live
Redis instance.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Dict, Optional

from shipsy_cache.l2.base import L2Backend


class InMemoryTestL2(L2Backend):
    """Small async in-memory L2 backend used only by the test suite."""

    def __init__(self) -> None:
        """Initialize backend state."""

        self._lock = asyncio.Lock()
        self._store: Dict[str, Dict[str, Any]] = {}

    async def get(self, key: str) -> Optional[Any]:
        """Return a fresh value for ``key`` or ``None`` when missing/expired."""

        async with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None

            if entry["expire_at"] is not None and entry["expire_at"] <= time.time():
                self._store.pop(key, None)
                return None

            return json.loads(entry["payload"])

    async def set(self, key: str, value: Any, ttl_seconds: float) -> None:
        """Store a JSON-serializable value under ``key``."""

        payload = json.dumps(value)
        expire_at = time.time() + ttl_seconds if ttl_seconds is not None else None
        async with self._lock:
            self._store[key] = {
                "payload": payload,
                "expire_at": expire_at,
                "created_at": time.time(),
            }

    async def delete(self, key: str) -> None:
        """Delete ``key`` if present."""

        async with self._lock:
            self._store.pop(key, None)

    async def clear(self) -> None:
        """Clear the entire test backend."""

        async with self._lock:
            self._store.clear()

    async def ping(self) -> bool:
        """Return ``True`` because the test backend is always reachable."""

        return True
