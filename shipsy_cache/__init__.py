"""Public package exports for shipsy_cache."""

from .cache import TieredCache
from .events import CacheEventEmitter
from .exceptions import CacheError, FactoryError, L2UnavailableError
from shipsy_cache.backends.fake_redis import FakeRedisL2
from .l2.memory_stub import MemoryStubL2
from .l2.redis_store import RedisL2
from .ttl import parse_ttl

__all__ = [
    "TieredCache",
    "RedisL2",
    "MemoryStubL2",
    "CacheEventEmitter",
    "CacheError",
    "L2UnavailableError",
    "FactoryError",
    "FakeRedisL2",
    "parse_ttl",
]

__version__ = "1.0.0"
