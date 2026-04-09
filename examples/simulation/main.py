"""Run a full behavior simulation for the TieredCache library.

Run:
    python examples/simulation/main.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from shipsy_cache import TieredCache

from logger import log
from scenarios import (
    cache_hit_scenario,
    cold_start_scenario,
    graceful_degradation_scenario,
    l2_hydration_scenario,
    stampede_scenario,
    ttl_expiry_scenario,
)


def attach_event_listeners(cache: TieredCache) -> None:
    """Attach real event listeners to the cache instance."""

    def listener(payload: Dict[str, Any]) -> None:
        message = (
            f"payload={payload} "
            f"key={payload.get('key')} "
            f"tier={payload.get('tier', '-')}"
        )
        log(payload["event"], message)

    for event_name in (
        "cache:hit",
        "cache:miss",
        "cache:set",
        "cache:stale-served",
        "cache:invalidate",
    ):
        cache.on(event_name, listener)


async def main() -> None:
    """Run all cache behavior scenarios sequentially."""

    cache = TieredCache(default_ttl="5s", grace_period="3s", namespace="simulation-demo")
    attach_event_listeners(cache)

    print("\n=== Cold Start Scenario ===")
    await cold_start_scenario(cache)

    print("\n=== Cache Hit Scenario ===")
    await cache_hit_scenario(cache)

    print("\n=== L2 Hydration Scenario ===")
    await l2_hydration_scenario(cache)

    print("\n=== Stampede Scenario ===")
    await stampede_scenario(cache)

    print("\n=== TTL Expiry Scenario ===")
    await ttl_expiry_scenario(cache)

    print("\n=== Graceful Degradation Scenario ===")
    await graceful_degradation_scenario(cache)

    print("\n=== Simulation Complete ===")
    log("RESULT", f"Final cache stats: {cache.stats()}")


if __name__ == "__main__":
    asyncio.run(main())
