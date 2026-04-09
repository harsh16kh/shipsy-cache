# Design Decisions

## 1. Language Choice: Python with asyncio
**Decision:** Python async/await  
**Alternatives considered:** Java, Node.js  
**Rationale:** The assignment explicitly calls for Python and native concurrency primitives. `asyncio` keeps the API lightweight and integrates naturally with network-bound L2 backends and async application code.  
**Tradeoffs:** Python does not offer the same raw throughput as JVM-based systems, and care is still required when mixing sync L1 code with async orchestration.

## 2. L1 Eviction: LRU vs TTL-Only
**Decision:** LRU + TTL combined  
**Alternatives considered:** TTL-only, FIFO, LFU  
**Rationale:** TTL alone does not bound memory usage. LRU provides a practical bounded-memory policy while TTL still enforces freshness.  
**Tradeoffs:** LRU adds bookkeeping overhead and can evict infrequently accessed but still-valid entries.

## 3. Stampede Protection: Per-Key asyncio.Lock
**Decision:** Dict of asyncio.Lock per key  
**Alternatives considered:** asyncio.Event, single global lock, Redis-based distributed lock  
**Rationale:** Per-key locks keep unrelated keys independent while preventing duplicate factory calls for the same key. It is simple, local, and aligned with the assignment scope.  
**Tradeoffs:** Protection is process-local, not distributed across multiple application instances.

## 4. Lazy vs Active TTL Eviction in L1
**Decision:** Lazy eviction on read  
**Rationale:** Lazy eviction avoids background housekeeping threads and keeps the library small and dependency-free. It is also sufficient for a library that runs embedded inside another application.  
**Tradeoffs:** Expired entries may remain in memory until touched, and memory usage is slightly less predictable than with active sweeping.

## 5. L2 Value Serialization: JSON
**Decision:** JSON serialization  
**Alternatives considered:** Pickle, MessagePack, Protobuf  
**Rationale:** JSON is portable, safe relative to pickle, human-inspectable, and good enough for the assignment’s value shapes.  
**Tradeoffs:** JSON only supports JSON-serializable data and may be less space-efficient than binary formats.

## 6. Grace Period Implementation
**Decision:** Store stale value in L1's get_stale(), check within grace window  
**Rationale:** Grace serving only needs local metadata, so L1 is the right place to preserve recently expired entries for fallback.  
**Tradeoffs:** Grace fallback is local to the process. A cold process cannot recover stale data unless it still exists in L2 and is fresh there.

## 7. Default L2: MemoryStub vs Redis
**Decision:** MemoryStub as default  
**Rationale:** Zero-dependency out of the box  
**Tradeoffs:** The default is process-local and not shared across instances, so teams need `RedisL2` when they want a shared L2 cache.

## 8. What I Would Change With More Time
- Active background TTL sweep for L1
- Metrics counters (hit rate, miss rate) exposed via stats()
- Redis Cluster support
- Key compression for large payloads
- Async L1 (currently uses threading.Lock for sync compatibility)
