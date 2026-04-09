"""Demonstrates stampede protection under concurrent load.
Launches 50 concurrent coroutines for the same cold key.
Shows factory called exactly once.
Run: python examples/stampede_demo.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shipsy_cache import TieredCache


async def main() -> None:
    """Run a concurrency demo for stampede protection."""

    cache = TieredCache(default_ttl=60, grace_period=10, namespace="stampede-demo")
    factory_calls = 0

    async def expensive_factory() -> str:
        nonlocal factory_calls
        factory_calls += 1
        print("Factory: computing hot_key from source of truth...")
        await asyncio.sleep(0.2)
        return "result_value"

    tasks = [cache.getOrSet("hot_key", expensive_factory, ttl=60) for _ in range(50)]
    results = await asyncio.gather(*tasks)

    print(f"Factory called: {factory_calls} time(s)")
    print(f"All callers received: {set(results)}")


if __name__ == "__main__":
    asyncio.run(main())
