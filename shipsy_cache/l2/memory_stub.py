"""In-process L2 backend for zero-dependency usage and testing."""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Dict, Optional

from .base import L2Backend


class MemoryStubL2(L2Backend):
    """A fully working in-process L2 backend with TTL support."""

    def __init__(self) -> None:
        """Initialize the in-memory backend state."""

        self._lock = asyncio.Lock()
        self._store: Dict[str, Dict[str, Any]] = {}

    async def get(self, key: str) -> Optional[Any]:
        """Return a fresh value for ``key`` or ``None`` when missing/expired."""

        async with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None

            if entry["expire_at"] <= time.time():
                self._store.pop(key, None)
                return None

            return json.loads(entry["payload"])

    async def set(self, key: str, value: Any, ttl_seconds: float) -> None:
        """Store a JSON-serializable value under ``key`` with TTL semantics."""

        payload = json.dumps(value)
        async with self._lock:
            self._store[key] = {
                "payload": payload,
                "expire_at": time.time() + ttl_seconds,
                "created_at": time.time(),
            }

    async def delete(self, key: str) -> None:
        """Delete ``key`` if it exists."""

        async with self._lock:
            self._store.pop(key, None)

    async def clear(self) -> None:
        """Clear the entire in-process backend."""

        async with self._lock:
            self._store.clear()

    async def ping(self) -> bool:
        """Return ``True`` because the in-process backend is always reachable."""

        return True
