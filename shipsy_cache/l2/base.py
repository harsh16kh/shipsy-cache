"""Abstract base interface for L2 cache backends."""

from __future__ import annotations

from dataclasses import dataclass
from abc import ABC, abstractmethod
from typing import Any, Optional


@dataclass(frozen=True)
class L2CacheEntry:
    """Value returned by an L2 backend along with optional expiry metadata."""

    value: Any
    remaining_ttl_seconds: Optional[float]


class L2Backend(ABC):
    """Abstract contract that all L2 cache backends must implement."""

    async def get(self, key: str) -> Optional[Any]:
        """Return the cached value for ``key`` or ``None`` when not found."""

        entry = await self.get_entry(key)
        if entry is None:
            return None
        return entry.value

    @abstractmethod
    async def get_entry(self, key: str) -> Optional[L2CacheEntry]:
        """Return the cached value and any available expiry metadata.

        Backends that cannot surface expiry metadata should return an entry with
        ``remaining_ttl_seconds=None``. Backends that can expose remaining TTL
        should populate it so L1 hydration can preserve freshness accurately.
        """

    @abstractmethod
    async def set(self, key: str, value: Any, ttl_seconds: float) -> None:
        """Persist ``value`` under ``key`` for ``ttl_seconds`` seconds."""

    @abstractmethod
    async def delete(self, key: str) -> None:
        """Delete ``key`` from the backend if it exists."""

    @abstractmethod
    async def clear(self) -> None:
        """Remove all entries controlled by this backend instance."""

    @abstractmethod
    async def ping(self) -> bool:
        """Return ``True`` when the backend is reachable and healthy."""
