# Setup & Operations Instructions

## Prerequisites

- Python 3.9 or newer
- `pip`
- Optional: Docker and Docker Compose for Redis-backed integration testing
- Optional: local or remote Redis instance for `RedisL2`

## Local Development Setup

```bash
python3 -m pip install -e ".[dev]"
```

Repository layout:

- `shipsy_cache/`: library source code
- `tests/`: unit and integration tests
- `examples/`: runnable demos
- `docker/`: local container setup for Redis-backed testing

## Running Without Redis (default stub)

The default `TieredCache()` constructor uses `MemoryStubL2`, which is fully in-process and needs no external services.

```python
from shipsy_cache import TieredCache

cache = TieredCache()
```

This is the recommended mode for local development, fast tests, and environments where a shared L2 is unnecessary.

## Running With Redis

Set the environment variables or pass constructor arguments explicitly:

```bash
export REDIS_HOST=localhost
export REDIS_PORT=6379
export REDIS_DB=0
export REDIS_PASSWORD=""
```

Then create the backend:

```python
from shipsy_cache import RedisL2, TieredCache

backend = RedisL2(namespace="shipsy_cache")
cache = TieredCache(l2_backend=backend, namespace="orders")
```

## Docker Setup

Run the full Redis-backed test environment:

```bash
docker compose -f docker/docker-compose.yml up --build --abort-on-container-exit
```

This starts:

- `redis`: Redis 7 with health checks
- `tests`: container that installs the package and runs pytest with coverage

## Environment Variables Reference

| Variable | Used By | Default | Purpose |
| --- | --- | --- | --- |
| `REDIS_HOST` | `RedisL2` | `localhost` | Redis hostname |
| `REDIS_PORT` | `RedisL2` | `6379` | Redis port |
| `REDIS_DB` | `RedisL2` | `0` | Redis database index |
| `REDIS_PASSWORD` | `RedisL2` | unset | Redis password |

## Configuration Options

`TieredCache` options:

- `l2_backend`: async L2 implementation, defaults to `MemoryStubL2`
- `l1_max_size`: bounded L1 capacity
- `default_ttl`: fallback TTL for writes
- `grace_period`: stale serving window after expiry
- `namespace`: logical application namespace
- `event_emitter`: custom event emitter instance

`RedisL2` options:

- `host`
- `port`
- `db`
- `password`
- `ssl`
- `namespace`
- `socket_timeout`

## Troubleshooting Common Issues

- `ModuleNotFoundError: No module named pytest`
  Install development dependencies with `python3 -m pip install -e ".[dev]"`.

- `L2UnavailableError` from Redis operations
  Check `REDIS_HOST`, `REDIS_PORT`, credentials, firewall rules, and whether Redis is healthy.

- Cache values disappear immediately
  Verify TTL units. `5m` means 5 minutes, while `5` means 5 seconds.

- Integration tests skip unexpectedly
  Ensure `REDIS_HOST` is set before invoking `pytest tests/integration/`.

## Running the Full Test Suite

Unit tests:

```bash
python3 -m pytest tests/ --ignore=tests/integration -v --cov=shipsy_cache --cov-report=term-missing
```

Integration tests:

```bash
export REDIS_HOST=localhost
python3 -m pytest tests/integration/ -v
```

## CI/CD Pipeline

The GitHub Actions workflow at `.github/workflows/ci.yml` performs:

- Unit tests across Python 3.9, 3.10, and 3.11
- Coverage enforcement with `--cov-fail-under=90`
- Redis-backed integration tests on Python 3.11 using a service container

## Adding a New L2 Backend (extension guide)

1. Implement `shipsy_cache.l2.base.L2Backend`.
2. Ensure values are serialized/deserialized as JSON-compatible data.
3. Respect TTL semantics in the backend.
4. Raise `L2UnavailableError` for connectivity/health failures.
5. Add targeted unit tests plus any backend-specific integration tests.
6. Export the backend from `shipsy_cache/l2/__init__.py` and optionally `shipsy_cache/__init__.py`.
