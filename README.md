# Shipsy Multi-Tier Caching Library

A production-quality, two-tier caching library built for high-throughput logistics backends. Designed as a take-home assignment for Shipsy Engineering.

## Quick Start

1. Install the demo extra.
2. Run the visual demo.
3. Watch the cache behavior play out live in the terminal.

```bash
pip install -e ".[demo]"
python examples/visual_demo.py
```

When you run the visual demo, you get a rich terminal dashboard demonstrating cache hits, stampede protection, TTL expiry, graceful degradation, and L2 hydration using logistics-realistic data. It uses `FakeRedisL2`, so there is no Redis container, Docker setup, or external dependency required to evaluate the library.

## Installation

```bash
# Core library (zero dependencies)
pip install -e .

# With visual demo support
pip install -e ".[demo]"

# With development tools (testing, linting)
pip install -e ".[dev]"
```

## Usage

### Cache-Aside

The simplest way to use the library is through `getOrSet()`. The example below shows the full `TieredCache(...)` constructor so every parameter is visible:

```python
import asyncio

from shipsy_cache import TieredCache


async def main() -> None:
    cache = TieredCache(
        l2_backend=None,
        l1_max_size=1000,
        default_ttl="5m",
        grace_period="30s",
        namespace="orders",
        event_emitter=None,
    )

    async def slow_database_lookup() -> dict[str, str]:
        await asyncio.sleep(0.2)
        return {"order_id": "ORD-1001", "status": "in_transit"}

    first = await cache.getOrSet("order:1001", slow_database_lookup, ttl="30s")
    second = await cache.getOrSet("order:1001", slow_database_lookup, ttl="30s")
    print(first)
    print(second)


asyncio.run(main())
```

### With Redis (Production)

```python
import asyncio

from shipsy_cache import RedisL2, TieredCache


async def main() -> None:
    l2 = RedisL2(
        host="localhost",
        port=6379,
        db=0,
        password=None,
        ssl=False,
        namespace="rates_backend",
        socket_timeout=2.0,
    )
    cache = TieredCache(
        l2_backend=l2,
        l1_max_size=1000,
        default_ttl="10m",
        grace_period="1m",
        namespace="rates",
        event_emitter=None,
    )

    rate = await cache.getOrSet(
        "delhivery:DEL:BLR",
        lambda: carrier_api.get_rate("delhivery", "DEL", "BLR"),
        ttl="15m",
    )
    print(rate)


asyncio.run(main())
```

### With FakeRedisL2 (Development, Demos, and Integration-Style Tests)

`FakeRedisL2` is the "Redis-like local simulator" backend. It is designed for development, demos, and integration-style tests. Unlike `MemoryStubL2`, it JSON-serializes values on write and deserializes them on read, which means it catches serialization bugs that would otherwise stay hidden until a real Redis deployment.

```python
from shipsy_cache import FakeRedisL2, TieredCache

l2 = FakeRedisL2(
    namespace="myservice_backend",
    latency_ms=5.0,
    failure_rate=0.0,
)
cache = TieredCache(
    l2_backend=l2,
    l1_max_size=500,
    default_ttl="10m",
    grace_period="1m",
    namespace="myservice",
    event_emitter=None,
)
```

### Backend Selection Guide

Use the backends by role rather than by "database count":

- `MemoryStubL2`: "default in-process backend" for zero-dependency usage and lightweight unit tests.
- `FakeRedisL2`: "Redis-like local simulator" for demos and tests that should cross a JSON serialization boundary and optionally simulate latency or failures.
- `RedisL2`: "production shared backend" for real multi-instance deployments.

```python
from shipsy_cache import FakeRedisL2, MemoryStubL2, RedisL2

default_local_backend = MemoryStubL2()
redis_like_local_backend = FakeRedisL2(namespace="demo", latency_ms=5.0, failure_rate=0.0)
production_shared_backend = RedisL2(
    host="localhost",
    port=6379,
    db=0,
    password=None,
    ssl=False,
    namespace="shipsy_cache",
    socket_timeout=2.0,
)
```

### Logistics Patterns

```python
# Rate shopping
rate = await cache.getOrSet(
    f"rate:{carrier}:{origin}:{dest}",
    lambda: carrier_api.get_rate(carrier, origin, dest),
    ttl="15m",
)

# Tracking (high read, short TTL)
status = await cache.getOrSet(
    f"tracking:{awb}",
    lambda: tracking_api.fetch(awb),
    ttl="30s",
)

# Serviceability (high read, long TTL)
result = await cache.getOrSet(
    f"serviceability:{pincode}",
    lambda: serviceability_db.check(pincode),
    ttl="6h",
)
```

### TTL Formats

| Input | Meaning | Output Seconds |
| --- | --- | ---: |
| `300` | numeric seconds | `300.0` |
| `30s` | 30 seconds | `30.0` |
| `5m` | 5 minutes | `300.0` |
| `2h` | 2 hours | `7200.0` |
| `1d` | 1 day | `86400.0` |

### Event Listening

```python
from shipsy_cache import TieredCache

cache = TieredCache(
    l2_backend=None,
    l1_max_size=1000,
    default_ttl="5m",
    grace_period="30s",
    namespace="events-demo",
    event_emitter=None,
)


def listener(payload: dict) -> None:
    print(payload)


cache.on("cache:hit", listener)
cache.on("cache:miss", listener)
cache.on("cache:set", listener)
cache.on("cache:stale-served", listener)
cache.on("cache:invalidate", listener)
```

## Visual Demo

```bash
pip install rich
python examples/visual_demo.py
```

The demo covers:

- Rate shopping: cold vs warm fetch with latency comparison
- Stampede protection: 50 concurrent requests, factory called once
- TTL lifecycle: live countdown showing fresh → expired transition
- Graceful degradation: stale serving during simulated carrier outage
- L2 → L1 hydration: simulating multi-instance deployment
- Event observability: full event stream display

The demo uses `FakeRedisL2` — no Docker, no Redis, no external services.

## Running Tests

### Unit Tests (no dependencies needed)

```bash
pytest tests/ --ignore=tests/integration -v --cov=shipsy_cache --cov-report=term-missing
```

### Integration Tests (requires Redis)

```bash
export REDIS_HOST=localhost REDIS_PORT=6379
pytest tests/integration/ -v
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

### FakeRedisL2(...)

```python
FakeRedisL2(
    namespace: str = "shipsy_cache",
    latency_ms: float = 0.0,
    failure_rate: float = 0.0,
)
```

In-process Redis simulator with JSON serialization, TTL support, configurable latency, and failure injection. Use for development, demos, and integration tests without a running Redis server.

## Architecture

### L1 — In-Memory Cache

L1 is a bounded `OrderedDict`-backed LRU with lazy TTL eviction and `threading.Lock` protection for sync-safe access.

### L2 — Pluggable Backend

L2 is an async interface. The library ships with three implementations: `MemoryStubL2` for unit tests, `FakeRedisL2` for integration tests and demos (with JSON serialization and configurable latency), and `RedisL2` for production deployments.

If you prefer plain-language naming:

- `MemoryStubL2` = default in-process backend
- `FakeRedisL2` = Redis-like local simulator
- `RedisL2` = production shared backend

### Cache-Aside Flow

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

### Stampede Protection

`getOrSet()` keeps a per-key `asyncio.Lock`. The first coroutine becomes the leader, and concurrent callers for the same key wait on that lock instead of calling the factory again.

### Grace Period

When a cached L1 value has expired, the library can still serve it for a short grace window if the factory fails. This protects callers during transient downstream outages.

## Configuration Reference

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
| `namespace` | `FakeRedisL2` | `"shipsy_cache"` | Key prefix, mirrors RedisL2 behavior |
| `latency_ms` | `FakeRedisL2` | `0.0` | Artificial delay per operation in ms |
| `failure_rate` | `FakeRedisL2` | `0.0` | Probability (0-1) of simulated `ConnectionError` |

## Key Design Decisions

See [DESIGN_DECISIONS.md](./DESIGN_DECISIONS.md).

## What I Would Change With More Time

- Preserve exact remaining TTL when hydrating L1 from L2 instead of resetting to `default_ttl`.
- Add richer stats such as hit rate, stale serves, and inflight contention counts.
- Add optional serializer hooks for teams that need MessagePack or custom encoding.
- Add more Redis-specific operational features such as circuit-breaking and cluster-aware tests.
- Add circuit-breaker pattern around L2 calls so a failing Redis doesn't add latency to every request.
- Support batch `getOrSet` for fetching multiple keys in a single call (common in rate-shopping where you need 6 carrier rates at once).

## How I Used AI

AI helped accelerate scaffolding, draft documentation, and generate an initial pass at the test suite and examples. I still had to review the concurrency semantics, refine the stale-serving behavior, and ensure the README and docs matched the actual implemented API rather than an aspirational one. The remaining area I would revisit manually is deeper production hardening around distributed Redis failure modes.
