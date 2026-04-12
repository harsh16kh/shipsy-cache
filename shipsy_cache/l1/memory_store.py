"""Thread-safe in-memory LRU cache implementation for L1."""

from __future__ import annotations

from dataclasses import dataclass
import threading
import time
from collections import OrderedDict
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class MemoryStoreEntry:
    """Entry metadata exposed for cache coordination logic."""

    value: Any
    expire_at: float
    created_at: float
    is_stale: bool


class MemoryStore:
    """A bounded, thread-safe LRU store with TTL-aware entries."""

    def __init__(self, max_size: int = 1000) -> None:
        """Initialize the store.

        Args:
            max_size: Maximum number of fresh entries to keep in memory.

        Raises:
            ValueError: If ``max_size`` is less than 1.
        """

        if max_size < 1:
            raise ValueError("max_size must be at least 1.")
        self.max_size = max_size
        self._lock = threading.Lock()
        self._store: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
        self._stale: Dict[str, Dict[str, Any]] = {}

    def get(self, key: str) -> Optional[Any]:
        """Return a fresh value for ``key`` or ``None``.

        Expired entries are lazily evicted from the active LRU store and kept
        available for ``get_stale`` lookups.

        Args:
            key: Cache key to read.

        Returns:
            The cached value when fresh, otherwise ``None``.
        """

        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None

            now = time.time()
            if entry["expire_at"] <= now:
                stale_entry = self._store.pop(key)
                self._stale[key] = stale_entry
                return None

            self._store.move_to_end(key)
            return entry["value"]

    def set(self, key: str, value: Any, ttl_seconds: float) -> None:
        """Store ``value`` under ``key`` with a TTL.

        Args:
            key: Cache key to write.
            value: Value to cache.
            ttl_seconds: Time to live in seconds.
        """

        now = time.time()
        entry = {
            "value": value,
            "expire_at": now + ttl_seconds,
            "created_at": now,
        }
        with self._lock:
            self._stale.pop(key, None)
            if key in self._store:
                self._store.pop(key)
            elif len(self._store) >= self.max_size:
                self._store.popitem(last=False)
            self._store[key] = entry

    def delete(self, key: str) -> None:
        """Delete ``key`` from both fresh and stale storage."""

        with self._lock:
            self._store.pop(key, None)
            self._stale.pop(key, None)

    def get_stale(self, key: str) -> Optional[Any]:
        """Return the cached value even if it is expired.

        Args:
            key: Cache key to inspect.

        Returns:
            The cached value if the key has ever been stored and not deleted,
            otherwise ``None``.
        """

        with self._lock:
            entry = self._store.get(key)
            if entry is not None:
                self._store.move_to_end(key)
                return entry["value"]

            stale_entry = self._stale.get(key)
            if stale_entry is not None:
                return stale_entry["value"]
            return None

    def clear(self) -> None:
        """Remove all fresh and stale entries from the store."""

        with self._lock:
            self._store.clear()
            self._stale.clear()

    def stats(self) -> Dict[str, int]:
        """Return basic store statistics."""

        with self._lock:
            return {
                "size": len(self._store),
                "max_size": self.max_size,
            }

    def get_entry_metadata(self, key: str) -> Optional[MemoryStoreEntry]:
        """Return fresh or stale entry metadata for cache coordination."""

        with self._lock:
            entry = self._store.get(key)
            if entry is not None:
                return MemoryStoreEntry(
                    value=entry["value"],
                    expire_at=entry["expire_at"],
                    created_at=entry["created_at"],
                    is_stale=False,
                )
            stale_entry = self._stale.get(key)
            if stale_entry is not None:
                return MemoryStoreEntry(
                    value=stale_entry["value"],
                    expire_at=stale_entry["expire_at"],
                    created_at=stale_entry["created_at"],
                    is_stale=True,
                )
            return None
