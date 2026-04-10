# Architecture

## Overview

`shipsy_cache` is a library-first, two-tier cache built around a local in-memory L1 and a pluggable async L2. The primary design target is read-through caching inside another Python application, not running as a standalone service. In caching literature this pattern is often called "cache-aside": the application asks the cache for a key, and on a miss the cache invokes a factory to rebuild and store the value.

## Component Diagram (ASCII art)

```text
+-------------------+
| Application Code  |
+---------+---------+
          |
          v
+-------------------+
|   TieredCache     |
| get / set /       |
| getOrSet / clear  |
+----+---------+----+
     |         |
     v         v
+---------+  +------------------+
| L1      |  | L2Backend        |
|Memory   |  | - RedisL2        |
|Store    |  +------------------+
+---------+
     |
     v
 stale metadata for grace-period serving
```

## L1 Cache: In-Memory LRU Store

### Data Structure

Fresh entries live in an `OrderedDict[str, dict]` with the shape:

```text
{
  "value": Any,
  "expire_at": float,
  "created_at": float
}
```

Expired entries are moved out of the active LRU map into a stale map so they can still participate in grace-period fallback.

### Eviction Policy

L1 combines:

- LRU for bounded memory usage
- TTL for freshness

When the active store is full, the least recently used fresh entry is evicted. Expired entries are lazily evicted on access.

### Thread Safety

L1 uses `threading.Lock` so it can be safely accessed even if the surrounding application mixes synchronous and asynchronous callers in the same process.

## L2 Cache: Pluggable Backend

### Interface Contract

All L2 backends implement:

- `get(key)`
- `set(key, value, ttl_seconds)`
- `delete(key)`
- `clear()`
- `ping()`

Backends are async because they may involve network I/O.

### Redis Implementation

`RedisL2` uses `redis.asyncio`, JSON serialization, and a storage namespace prefix. All backend exceptions are translated into `L2UnavailableError`.

`RedisL2` is the shipped L2 driver. It handles JSON serialization, native Redis expiration, and health checking through `PING`.

## Cache-Aside Flow

### Read Path (step-by-step with ASCII flowchart)

```text
get(key)
  |
  +--> L1.get()
  |      |
  |      +--> fresh hit --> emit cache:hit(L1) --> return
  |
  +--> L2.get()
         |
         +--> hit --> L1.set() --> emit cache:hit(L2) --> return
         |
         +--> miss or unavailable --> emit cache:miss --> return None
```

### Write Path

`set()` writes to L1 and L2 concurrently with `asyncio.gather()`. Public writes propagate L2 failures so callers can decide how to react.

### Invalidation Path

`invalidate()` removes a single key from both tiers. `clear()` removes everything from both tiers.

## Stampede Protection

### Problem Statement

Without coordination, many concurrent callers can all miss a cold key and hammer the source of truth simultaneously.

### Solution: Per-Key asyncio.Lock

`TieredCache.getOrSet()` stores an `asyncio.Lock` per namespaced key. The first caller acquires the lock and runs the factory. Concurrent callers wait for that lock, then reuse the leader's result or freshly populated cache entry.

### Sequence Diagram (ASCII)

```text
Caller A             TieredCache              Caller B
   |                      |                      |
   | getOrSet(key)        |                      |
   |--------------------->|                      |
   |                      | create/acquire lock  |
   |                      | run factory          |
   |                      |<---------------------|
   |                      |   getOrSet(key)      |
   |                      |   sees lock locked   |
   |                      |   waits              |
   |                      | store result         |
   |<---------------------|                      |
   | return value         | release lock         |
   |                      |--------------------->|
   |                      | Caller B reuses result
```

### Race Conditions Addressed

- Double factory execution for the same key under concurrency
- Re-checking cache after lock acquisition in case another coroutine populated it first
- Reusing the leader result for waiting coroutines

## Grace Period & Graceful Degradation

### Scenarios Handled

- Factory fails after L1 entry expired
- L2 becomes unavailable during reads
- L2 becomes unavailable during a `getOrSet()` write-back path

### Behavior Table

| Scenario | Behavior |
| --- | --- |
| L1 fresh hit | Return immediately |
| L1 expired, factory fails, stale within grace | Return stale and emit `cache:stale-served` |
| L1 expired, factory fails, stale beyond grace | Raise `FactoryError` |
| L2 unavailable on `get()` and no L1 hit | Return miss |
| L2 unavailable during `getOrSet()` write-back | Keep L1 populated and return result |

## TTL Management

### L1 TTL: Lazy Eviction

L1 does not run a sweeper thread. Instead, entries are checked on access and moved to stale storage when expired.

### L2 TTL: Native Redis EXPIRE

`RedisL2` delegates expiry to Redis using native expiration on write.

### Grace Period vs TTL

TTL controls freshness. Grace period is additional tolerance after expiry, but only for fallback during factory failure. A stale value is never returned on a normal successful refresh path.

## Event System

### Event Types

- `cache:hit`
- `cache:miss`
- `cache:set`
- `cache:stale-served`
- `cache:invalidate`

### Payload Schema

```text
{
  "event": str,
  "key": str,
  "tier": str,        # optional
  "timestamp": float
}
```

### Usage Patterns

- Logging cache effectiveness
- Debugging behavior in integration environments
- Lightweight application-level observability hooks without adding telemetry dependencies

## Scalability Considerations

### Horizontal Scaling Behavior

Each application instance owns its own L1. With Redis, instances can still share L2 data but not local L1 contents.

### L1 is Local, L2 is Shared

This is intentional. L1 optimizes process-local latency; L2 provides cross-instance reuse and resilience to local evictions.

### Redis Cluster Compatibility

The current Redis implementation targets a single logical Redis endpoint. Additional cluster-aware routing and operational testing would be needed for large deployments.

## Security

### Credential Management

Redis credentials come from constructor arguments or environment variables. No credentials are hard-coded.

### Namespace Isolation

Two layers of namespacing exist:

- `TieredCache.namespace` for logical application isolation
- `RedisL2.namespace` for backend storage isolation

### PII Considerations

This library does not inspect payload contents. Applications should avoid caching sensitive data without explicit TTL, namespace, and data-retention decisions.
