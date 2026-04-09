"""Redis-backed L2 cache implementation."""

from __future__ import annotations

import json
import os
from math import ceil
from typing import Any, Optional

from ..exceptions import L2UnavailableError
from .base import L2Backend

try:  # pragma: no cover - import availability depends on environment
    import redis.asyncio as redis
    from redis.exceptions import RedisError
except ImportError:  # pragma: no cover - handled at runtime
    redis = None
    RedisError = Exception


class RedisL2(L2Backend):
    """Async Redis L2 backend with JSON serialization and namespacing."""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6379,
        db: int = 0,
        password: Optional[str] = None,
        ssl: bool = False,
        namespace: str = "shipsy_cache",
        socket_timeout: float = 2.0,
    ) -> None:
        """Initialize a Redis client using constructor values or environment variables."""

        if redis is None:
            raise RuntimeError("redis[asyncio] must be installed to use RedisL2.")

        resolved_host = os.getenv("REDIS_HOST", host)
        resolved_port = int(os.getenv("REDIS_PORT", str(port)))
        resolved_db = int(os.getenv("REDIS_DB", str(db)))
        resolved_password = os.getenv("REDIS_PASSWORD", password)

        self.namespace = namespace
        self._client = redis.Redis(
            host=resolved_host,
            port=resolved_port,
            db=resolved_db,
            password=resolved_password,
            ssl=ssl,
            socket_timeout=socket_timeout,
            decode_responses=True,
        )

    async def get(self, key: str) -> Optional[Any]:
        """Return the deserialized value for ``key`` or ``None`` when absent."""

        try:
            raw_value = await self._client.get(self._prefix(key))
            if raw_value is None:
                return None
            return json.loads(raw_value)
        except RedisError as exc:
            raise L2UnavailableError("Redis backend is unavailable during get().") from exc

    async def set(self, key: str, value: Any, ttl_seconds: float) -> None:
        """Store a JSON-serializable value in Redis with native expiration."""

        try:
            payload = json.dumps(value)
            await self._client.set(self._prefix(key), payload, px=max(1, ceil(ttl_seconds * 1000)))
        except RedisError as exc:
            raise L2UnavailableError("Redis backend is unavailable during set().") from exc

    async def delete(self, key: str) -> None:
        """Delete a Redis key if it exists."""

        try:
            await self._client.delete(self._prefix(key))
        except RedisError as exc:
            raise L2UnavailableError("Redis backend is unavailable during delete().") from exc

    async def clear(self) -> None:
        """Delete all keys owned by this backend namespace."""

        pattern = f"{self.namespace}:*"
        try:
            cursor = 0
            while True:
                cursor, keys = await self._client.scan(cursor=cursor, match=pattern, count=100)
                if keys:
                    await self._client.delete(*keys)
                if cursor == 0:
                    break
        except RedisError as exc:
            raise L2UnavailableError("Redis backend is unavailable during clear().") from exc

    async def ping(self) -> bool:
        """Run a Redis PING health check."""

        try:
            return bool(await self._client.ping())
        except RedisError as exc:
            raise L2UnavailableError("Redis backend is unavailable during ping().") from exc

    def _prefix(self, key: str) -> str:
        """Return the namespaced Redis storage key."""

        return f"{self.namespace}:{key}"
