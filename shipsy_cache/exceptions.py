"""Custom exception types for the Shipsy cache library."""


class CacheError(Exception):
    """Base exception for all cache-related errors."""


class L2UnavailableError(CacheError):
    """Raised when the configured L2 backend is unreachable or unhealthy."""


class FactoryError(CacheError):
    """Raised when the factory callable fails and no stale value can be served."""
