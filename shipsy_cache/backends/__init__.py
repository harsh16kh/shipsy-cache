"""Backend compatibility layer for cache storage implementations."""

from .base import L2Backend
from .fake_redis import FakeRedisL2

__all__ = ["FakeRedisL2", "L2Backend"]
