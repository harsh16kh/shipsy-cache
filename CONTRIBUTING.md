# Contributing

## Development Setup

```bash
python3 -m pip install -e ".[dev]"
```

## Running Tests

```bash
python3 -m pytest tests/ --ignore=tests/integration -v --cov=shipsy_cache --cov-report=term-missing
```

Integration tests:

```bash
export REDIS_HOST=localhost
python3 -m pytest tests/integration/ -v
```

## Code Style (PEP 8, type hints required)

- Follow PEP 8
- Add type hints to all function signatures
- Add docstrings to public classes and methods
- Keep external dependencies minimal

## Adding a New L2 Backend

1. Implement `shipsy_cache.l2.base.L2Backend`.
2. Use JSON-compatible values or clearly document serialization constraints.
3. Raise `L2UnavailableError` for connectivity and backend health failures.
4. Add tests for TTL, deletion, clear behavior, and health checks.

## Pull Request Guidelines

- Keep changes scoped and reviewed
- Add or update tests for behavior changes
- Update README or architecture docs if the public API changes
- Avoid breaking import paths without a migration note

## Architecture Rules (no HTTP endpoints, no telemetry integrations, no distributed bus)

- This repository is a library, not a service
- Do not add HTTP endpoints or service wrappers
- Do not add telemetry SDK integrations
- Do not add distributed event buses or message brokers
