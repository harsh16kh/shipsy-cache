"""Public package exports for shipsy_cache."""

from .cache import TieredCache
from .events import CacheEventEmitter
from .exceptions import CacheError, FactoryError, L2UnavailableError
from .l2.redis_store import RedisL2
from .ttl import parse_ttl

__all__ = [
    "TieredCache",
    "RedisL2",
    "CacheEventEmitter",
    "CacheError",
    "L2UnavailableError",
    "FactoryError",
    "parse_ttl",
]

__version__ = "1.0.0"
