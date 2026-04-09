# Changelog

## [1.0.0] - Initial Release

### Added
- TieredCache core class with L1 + L2 architecture
- In-memory LRU L1 store with TTL support
- Redis L2 backend (redis.asyncio)
- In-process MemoryStub L2 (zero dependencies)
- getOrSet factory pattern
- Stampede protection via per-key asyncio.Lock
- Grace period for stale data serving
- Human-readable TTL parsing (30m, 2h, 1d)
- Event emitter (cache:hit, cache:miss, cache:set, cache:stale-served, cache:invalidate)
- Namespace support for key isolation
- Full test suite (unit + integration)
- Docker Compose for local Redis testing
- GitHub Actions CI pipeline
