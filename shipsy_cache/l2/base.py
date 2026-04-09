"""Abstract base interface for L2 cache backends."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional


class L2Backend(ABC):
    """Abstract contract that all L2 cache backends must implement."""

    @abstractmethod
    async def get(self, key: str) -> Optional[Any]:
        """Return the cached value for ``key`` or ``None`` when not found."""

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
