# Shipsy Multi-Tier Caching Library

A production-quality, two-tier caching library built for high-throughput logistics backends. Designed as a take-home assignment for Shipsy Engineering.

## Quick Start

1. Install the library.
2. Start Redis.
3. Import `TieredCache` into your service and start caching reads.

```bash
docker compose -f docker/docker-compose.yml up redis -d
pip install -e .
```

This path keeps the first experience focused on the library itself: `TieredCache`, `RedisL2`, TTLs, invalidation, and stampede protection. The visual demo still exists, but it is optional and moved to the end of this README.

## Installation

```bash
# Core library
pip install -e .

# With visual demo support
pip install -e ".[demo]"

# With development tools (testing, linting)
pip install -e ".[dev]"
```

## Prerequisites

- Python 3.9 or newer
- `pip`
- Redis for the production/backend path and integration tests
- Optional: Docker and Docker Compose for local Redis-backed testing

## Usage

### Cache-Aside

The simplest way to use the library is through `getOrSet()`. This example shows the full `RedisL2(...)` and `TieredCache(...)` setup so every parameter is visible in one place:

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
        namespace="orders_backend",
        socket_timeout=2.0,
    )
    cache = TieredCache(
        l2_backend=l2,
        l1_max_size=1000,
        default_ttl="10m",
        grace_period="1m",
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

## Operations Notes

### Redis Environment Variables

| Variable | Used By | Default | Purpose |
| --- | --- | --- | --- |
| `REDIS_HOST` | `RedisL2` | `localhost` | Redis hostname |
| `REDIS_PORT` | `RedisL2` | `6379` | Redis port |
| `REDIS_DB` | `RedisL2` | `0` | Redis database index |
| `REDIS_PASSWORD` | `RedisL2` | unset | Redis password |

### Troubleshooting

- `L2UnavailableError`: Check Redis reachability, credentials, and whether the target Redis instance is healthy.
- Cache entries expiring too quickly: Verify TTL units. `5m` means 5 minutes, while `5` means 5 seconds.
- Integration tests being skipped: Ensure `REDIS_HOST` is set before running `pytest tests/integration/`.

### CI/CD

GitHub Actions runs the workflow in [tests.yml](./.github/workflows/tests.yml):

- unit tests on Python 3.10
- Redis-backed integration tests on Python 3.10 using a service container

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

Fresh entries are tracked with:

```text
{
  "value": Any,
  "expire_at": float,
  "created_at": float
}
```

This gives the library bounded memory usage, fast process-local reads, and enough metadata to support stale serving during the grace window.

### L2 — Pluggable Backend

L2 is an async interface. This library currently ships with `RedisL2` as the working shared backend implementation.

The backend contract is:

- `get(key)`
- `set(key, value, ttl_seconds)`
- `delete(key)`
- `clear()`
- `ping()`

`RedisL2` uses `redis.asyncio`, JSON serialization, native Redis expiration, and exception translation into `L2UnavailableError`.

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

This keeps unrelated keys independent while preventing duplicate work for the same hot key. It is intentionally process-local and stays within the assignment scope.

### Grace Period

When a cached L1 value has expired, the library can still serve it for a short grace window if the factory fails. This protects callers during transient downstream outages.

### Scalability Notes

- L1 is local to each process.
- L2 is the shared layer across instances.
- Horizontal scaling works by sharing Redis while keeping fast local L1 reads per instance.
- Redis cluster-specific routing and operational hardening would be a next step for larger deployments.

### Security Notes

- Redis credentials are provided via constructor arguments or environment variables.
- No credentials are hard-coded.
- Namespace isolation exists at both the `TieredCache` layer and the `RedisL2` storage layer.

## Configuration Reference

| Option | Where | Default | Description |
| --- | --- | --- | --- |
| `l2_backend` | `TieredCache` | `RedisL2()` | Async L2 backend implementation |
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

## Key Design Decisions

- **Python with `asyncio`**: keeps the API natural for async application code and network-bound L2 backends without introducing external locking libraries.
- **L1 uses LRU plus TTL**: TTL alone does not bound memory usage, so LRU handles capacity while TTL handles freshness.
- **Per-key `asyncio.Lock` for stampede protection**: prevents duplicate factory calls for the same key while keeping unrelated keys independent.
- **Lazy eviction in L1**: avoids sweeper threads and keeps the library small, at the cost of leaving expired entries in memory until they are touched.
- **JSON serialization in L2**: portable, inspectable, and safer than pickle for a library submission, with the tradeoff that values must be JSON-serializable.
- **Grace-period fallback from L1 stale data**: lets the cache serve slightly old data during downstream failures without expanding the design into a distributed recovery mechanism.
- **Single shipped L2 driver: Redis**: keeps the submission focused while still preserving a pluggable backend contract for future extensions.

## What I Would Change With More Time

- Preserve exact remaining TTL when hydrating L1 from L2 instead of resetting to `default_ttl`.
- Add richer stats such as hit rate, stale serves, and inflight contention counts.
- Add optional serializer hooks for teams that need MessagePack or custom encoding.
- Add more Redis-specific operational features such as circuit-breaking and cluster-aware tests.
- Add circuit-breaker pattern around L2 calls so a failing Redis doesn't add latency to every request.
- Support batch `getOrSet` for fetching multiple keys in a single call (common in rate-shopping where you need 6 carrier rates at once).

## How I Used AI

AI helped accelerate scaffolding, draft documentation, and generate an initial pass at the test suite and examples. I still had to review the concurrency semantics, refine the stale-serving behavior, and ensure the README and docs matched the actual implemented API rather than an aspirational one. The remaining area I would revisit manually is deeper production hardening around distributed Redis failure modes.

## Visual Demo

```bash
pip install -e ".[demo]"
python examples/visual_demo.py
```

The visual demo is optional. It lives at the end of the README because it is not required to understand or use the library itself.

The demo covers:

- Rate shopping: cold vs warm fetch with latency comparison
- Stampede protection: 50 concurrent requests, factory called once
- TTL lifecycle: live countdown showing fresh → expired transition
- Graceful degradation: stale serving during simulated carrier outage
- L2 → L1 hydration: simulating multi-instance deployment
- Event observability: full event stream display

Internally, the demo uses a private demo-only backend so it can run without Docker, Redis, or external services.
