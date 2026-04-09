# Shipsy Multi-Tier Caching Library

> A production-quality two-tier caching library built for Shipsy Engineering's take-home assignment.

## Quick Start

```bash
pip install -e .
python3 examples/basic_usage.py
```

## Installation

```bash
pip install -e .
pip install -e ".[dev]"
```

## Usage

### Basic Usage (code example)

```python
import asyncio

from shipsy_cache import TieredCache


async def main() -> None:
    cache = TieredCache(default_ttl="5m", grace_period="30s")

    async def fetch_order() -> dict[str, str]:
        await asyncio.sleep(0.2)
        return {"order_id": "ORD-42", "status": "dispatched"}

    first = await cache.getOrSet("order:42", fetch_order, ttl="30s")
    second = await cache.getOrSet("order:42", fetch_order, ttl="30s")

    print(first)
    print(second)


asyncio.run(main())
```

### With Redis L2 (code example)

```python
import asyncio

from shipsy_cache import RedisL2, TieredCache


async def main() -> None:
    redis_backend = RedisL2(namespace="shipsy_cache")
    cache = TieredCache(
        l2_backend=redis_backend,
        namespace="rates",
        default_ttl="10m",
        grace_period="1m",
    )

    await cache.set("carrier:123", {"amount": 87.5, "currency": "INR"}, ttl="2m")
    print(await cache.get("carrier:123"))


asyncio.run(main())
```

### TTL Formats (table showing all supported formats)

| Input | Meaning | Output Seconds |
| --- | --- | ---: |
| `300` | numeric seconds | `300.0` |
| `30s` | 30 seconds | `30.0` |
| `5m` | 5 minutes | `300.0` |
| `2h` | 2 hours | `7200.0` |
| `1d` | 1 day | `86400.0` |

### Event Listening (code example)

```python
from shipsy_cache import TieredCache

cache = TieredCache()

def listener(payload: dict) -> None:
    print(payload)

cache.on("cache:hit", listener)
cache.on("cache:miss", listener)
cache.on("cache:set", listener)
cache.on("cache:stale-served", listener)
cache.on("cache:invalidate", listener)
```

## Running Tests

### Unit Tests (no dependencies needed)

```bash
python3 -m pytest tests/ --ignore=tests/integration -v --cov=shipsy_cache --cov-report=term-missing
```

### Integration Tests (with Redis)

```bash
export REDIS_HOST=localhost
export REDIS_PORT=6379
python3 -m pytest tests/integration/ -v
```

### Using Docker Compose

```bash
docker compose -f docker/docker-compose.yml up --build --abort-on-container-exit
```

## API Reference

### TieredCache(...)

```python
TieredCache(
    l2_backend: Optional[L2Backend] = None,
    l1_max_size: int = 1000,
    default_ttl: Union[int, float, str] = 300,
    grace_period: Union[int, float, str] = 60,
    namespace: str = "default",
    event_emitter: Optional[CacheEventEmitter] = None,
)
```

### cache.getOrSet(key, factory_fn, ttl)

Async cache-aside helper with per-key stampede protection. It checks L1, then L2, then runs `factory_fn()` exactly once for a cold key across concurrent coroutines.

### cache.get(key)

Async read path. Checks L1 first and falls back to L2. Returns `None` on miss.

### cache.set(key, value, ttl)

Async write path. Stores the value in both tiers, using `default_ttl` when `ttl` is omitted.

### cache.invalidate(key)

Async invalidation for a single logical key across both tiers.

### cache.clear()

Async full-cache clear across L1 and the configured L2 backend.

### cache.on(event, callback)

Registers a listener on the internal event emitter.

### cache.stats()

Returns `{"l1": {"size": int, "max_size": int}, "namespace": str}`.

## Architecture

### L1 — In-Memory Cache

L1 is a bounded `OrderedDict`-backed LRU with lazy TTL eviction and `threading.Lock` protection for sync-safe access.

### L2 — Pluggable Backend

L2 is an async interface. The package ships with a default `MemoryStubL2` for zero-dependency usage and `RedisL2` for shared cache deployments.

### Cache-Aside Flow (ASCII diagram)

```text
Caller
  |
  v
TieredCache.getOrSet(key)
  |
  +--> L1 fresh hit? ------ yes --> return value
  |
  +--> L2 fresh hit? ------ yes --> hydrate L1 --> return value
  |
  +--> acquire per-key lock
          |
          +--> another leader already computing? --> wait --> reuse populated value
          |
          +--> call factory_fn()
                  |
                  +--> success --> write L1 + L2 --> return value
                  |
                  +--> failure --> serve stale within grace window or raise FactoryError
```

### Stampede Protection (explanation)

`getOrSet()` keeps a per-key `asyncio.Lock`. The first coroutine becomes the leader, and concurrent callers for the same key wait on that lock instead of calling the factory again.

### Grace Period (explanation)

When a cached L1 value has expired, the library can still serve it for a short grace window if the factory fails. This protects callers during transient downstream outages.

## Key Design Decisions

See [DESIGN_DECISIONS.md](./DESIGN_DECISIONS.md).

## What I Would Change With More Time

- Preserve exact remaining TTL when hydrating L1 from L2 instead of resetting to `default_ttl`.
- Add richer stats such as hit rate, stale serves, and inflight contention counts.
- Add optional serializer hooks for teams that need MessagePack or custom encoding.
- Add more Redis-specific operational features such as circuit-breaking and cluster-aware tests.

## How I Used AI

AI helped accelerate scaffolding, draft documentation, and generate an initial pass at the test suite and examples. I still had to review the concurrency semantics, refine the stale-serving behavior, and ensure the README and docs matched the actual implemented API rather than an aspirational one. The remaining area I would revisit manually is deeper production hardening around distributed Redis failure modes.

## Configuration Reference (table of all config options)

| Option | Where | Default | Description |
| --- | --- | --- | --- |
| `l2_backend` | `TieredCache` | `MemoryStubL2()` | Async L2 backend implementation |
| `l1_max_size` | `TieredCache` | `1000` | Maximum fresh entries in local L1 |
| `default_ttl` | `TieredCache` | `300` | Default TTL for writes; accepts numbers or strings like `5m` |
| `grace_period` | `TieredCache` | `60` | Window for serving stale L1 data after expiry |
| `namespace` | `TieredCache` | `"default"` | Logical prefix for internal cache keys |
| `event_emitter` | `TieredCache` | `CacheEventEmitter()` | Optional custom event emitter |
| `host` | `RedisL2` | `"localhost"` | Redis host, overridden by `REDIS_HOST` |
| `port` | `RedisL2` | `6379` | Redis port, overridden by `REDIS_PORT` |
| `db` | `RedisL2` | `0` | Redis database index, overridden by `REDIS_DB` |
| `password` | `RedisL2` | `None` | Redis password, overridden by `REDIS_PASSWORD` |
| `ssl` | `RedisL2` | `False` | Whether to use TLS for Redis |
| `namespace` | `RedisL2` | `"shipsy_cache"` | Redis storage prefix applied ahead of logical cache keys |
| `socket_timeout` | `RedisL2` | `2.0` | Redis socket timeout in seconds |
