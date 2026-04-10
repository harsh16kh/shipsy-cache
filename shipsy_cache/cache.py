"""Tiered cache orchestration logic."""

from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Callable, Dict, Optional, Tuple, Union

from .events import CacheEventEmitter
from .exceptions import FactoryError, L2UnavailableError
from .l1.memory_store import MemoryStore
from .l2.base import L2Backend
from .l2.redis_store import RedisL2
from .ttl import parse_ttl


FactoryCallable = Callable[[], Awaitable[Any]]
TTLInput = Union[int, float, str, None]


class TieredCache:
    """Two-tier cache with in-memory L1, pluggable L2, and stampede protection."""

    def __init__(
        self,
        l2_backend: Optional[L2Backend] = None,
        l1_max_size: int = 1000,
        default_ttl: Union[int, float, str] = 300,
        grace_period: Union[int, float, str] = 60,
        namespace: str = "default",
        event_emitter: Optional[CacheEventEmitter] = None,
    ) -> None:
        """Initialize the tiered cache.

        Args:
            l2_backend: Optional L2 backend. Defaults to ``RedisL2``.
            l1_max_size: Maximum size for the L1 in-memory cache.
            default_ttl: Default TTL for writes when no override is provided.
            grace_period: Additional time window for serving stale values after
                expiry when the factory callable fails.
            namespace: Logical namespace used to isolate keys.
            event_emitter: Optional emitter for cache lifecycle events.
        """

        self.namespace = namespace
        self._default_ttl_seconds = parse_ttl(default_ttl)
        self._grace_period_seconds = parse_ttl(grace_period)
        self._l1 = MemoryStore(max_size=l1_max_size)
        self._l2 = l2_backend or RedisL2()
        self._events = event_emitter or CacheEventEmitter()
        self._inflight: Dict[str, asyncio.Lock] = {}
        self._inflight_results: Dict[str, Tuple[bool, Any]] = {}
        self._inflight_waiters: Dict[str, int] = {}

    async def get(self, key: str) -> Optional[Any]:
        """Return a fresh value from L1 or L2.

        Args:
            key: Application-level cache key.

        Returns:
            Cached value or ``None`` when the key is absent/expired.
        """

        namespaced_key = self._namespaced_key(key)

        l1_value = self._l1.get(namespaced_key)
        if l1_value is not None:
            self._emit("cache:hit", key, tier="L1")
            return l1_value

        try:
            l2_value = await self._l2.get(namespaced_key)
        except L2UnavailableError:
            self._emit("cache:miss", key)
            return None

        if l2_value is not None:
            self._l1.set(namespaced_key, l2_value, self._default_ttl_seconds)
            self._emit("cache:hit", key, tier="L2")
            return l2_value

        self._emit("cache:miss", key)
        return None

    async def set(self, key: str, value: Any, ttl: TTLInput = None) -> None:
        """Write a value to both cache tiers.

        Args:
            key: Application-level cache key.
            value: Value to store.
            ttl: Optional TTL override.
        """

        await self._set_internal(key, value, ttl=ttl, suppress_l2_errors=False)
        self._emit("cache:set", key, tier="L1+L2")

    async def invalidate(self, key: str) -> None:
        """Delete a key from both tiers.

        Args:
            key: Application-level cache key.
        """

        namespaced_key = self._namespaced_key(key)
        self._l1.delete(namespaced_key)
        await self._l2.delete(namespaced_key)
        self._emit("cache:invalidate", key, tier="L1+L2")

    async def clear(self) -> None:
        """Clear both cache tiers."""

        self._l1.clear()
        await self._l2.clear()

    async def getOrSet(self, key: str, factory_fn: FactoryCallable, ttl: TTLInput = None) -> Any:
        """Fetch from cache or compute once with per-key stampede protection.

        Args:
            key: Application-level cache key.
            factory_fn: Async callable used to build the value on cache miss.
            ttl: Optional TTL override for populated results.

        Returns:
            The cached or computed value.

        Raises:
            FactoryError: If the factory fails and no stale value is available
                within the configured grace period.
        """

        cached_value = await self.get(key)
        if cached_value is not None:
            return cached_value

        namespaced_key = self._namespaced_key(key)
        if namespaced_key not in self._inflight:
            self._inflight[namespaced_key] = asyncio.Lock()
            self._inflight_waiters[namespaced_key] = 0

        lock = self._inflight[namespaced_key]
        if lock.locked():
            self._inflight_waiters[namespaced_key] += 1
            try:
                async with lock:
                    inflight_result = self._inflight_results.get(namespaced_key)
                    if inflight_result is not None:
                        success, payload = inflight_result
                        if success:
                            return payload
                        raise payload

                    cached_after_wait = await self.get(key)
                    if cached_after_wait is not None:
                        return cached_after_wait

                    stale_value = self._get_stale_within_grace(namespaced_key)
                    if stale_value is not None:
                        return stale_value

                    raise FactoryError(
                        f"Cache value for key '{key}' was not populated by the inflight request.",
                    )
            finally:
                self._inflight_waiters[namespaced_key] -= 1
                self._cleanup_inflight(namespaced_key)

        try:
            async with lock:
                cached_after_lock = await self.get(key)
                if cached_after_lock is not None:
                    self._inflight_results[namespaced_key] = (True, cached_after_lock)
                    return cached_after_lock

                try:
                    result = await factory_fn()
                except Exception as exc:
                    stale_value = self._get_stale_within_grace(namespaced_key)
                    if stale_value is not None:
                        self._inflight_results[namespaced_key] = (True, stale_value)
                        self._emit("cache:stale-served", key, tier="L1")
                        return stale_value

                    error = FactoryError(
                        f"Factory callable failed for key '{key}' and no stale value was available.",
                    )
                    self._inflight_results[namespaced_key] = (False, error)
                    raise error from exc

                await self._set_internal(key, result, ttl=ttl, suppress_l2_errors=True)
                self._inflight_results[namespaced_key] = (True, result)
                self._emit("cache:set", key, tier="L1+L2")
                return result
        finally:
            self._cleanup_inflight(namespaced_key)

    def on(self, event: str, callback: Callable[..., Any]) -> None:
        """Register an event listener.

        Args:
            event: Event name such as ``"cache:hit"``.
            callback: Listener callback to invoke when the event fires.
        """

        self._events.on(event, callback)

    def stats(self) -> Dict[str, Any]:
        """Return cache statistics."""

        return {
            "l1": self._l1.stats(),
            "namespace": self.namespace,
        }

    def _namespaced_key(self, key: str) -> str:
        """Return the internal namespaced cache key."""

        return f"{self.namespace}:{key}"

    async def _set_internal(
        self,
        key: str,
        value: Any,
        ttl: TTLInput,
        suppress_l2_errors: bool,
    ) -> None:
        """Write to L1 and L2, optionally suppressing L2 failures."""

        ttl_seconds = self._default_ttl_seconds if ttl is None else parse_ttl(ttl)
        namespaced_key = self._namespaced_key(key)

        async def _write_l1() -> None:
            self._l1.set(namespaced_key, value, ttl_seconds)

        try:
            await asyncio.gather(
                _write_l1(),
                self._l2.set(namespaced_key, value, ttl_seconds),
            )
        except L2UnavailableError:
            if not suppress_l2_errors:
                raise
            self._l1.set(namespaced_key, value, ttl_seconds)

    def _get_stale_within_grace(self, namespaced_key: str) -> Optional[Any]:
        """Return stale L1 data only if it is still within the grace period."""

        entry = self._l1._get_entry(namespaced_key)
        if entry is None:
            return None

        if entry["expire_at"] + self._grace_period_seconds < time.time():
            return None

        return entry["value"]

    def _emit(self, event: str, key: str, tier: Optional[str] = None) -> None:
        """Emit a structured cache lifecycle event."""

        payload: Dict[str, Any] = {
            "event": event,
            "key": key,
            "timestamp": time.time(),
        }
        if tier is not None:
            payload["tier"] = tier
        self._events.emit(event, payload)

    def _cleanup_inflight(self, namespaced_key: str) -> None:
        """Release inflight bookkeeping once the last waiter has finished."""

        lock = self._inflight.get(namespaced_key)
        waiters = self._inflight_waiters.get(namespaced_key, 0)
        if lock is None:
            return

        if not lock.locked() and waiters == 0:
            self._inflight.pop(namespaced_key, None)
            self._inflight_waiters.pop(namespaced_key, None)
            self._inflight_results.pop(namespaced_key, None)
