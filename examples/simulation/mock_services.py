"""Async service simulators used by the cache behavior demo."""

from __future__ import annotations

import asyncio
import random
import time
from typing import Any, Dict


async def fetch_rate(origin: str, destination: str) -> Dict[str, Any]:
    """Simulate an async rate lookup with latency and dynamic pricing.

    Args:
        origin: Route origin.
        destination: Route destination.

    Returns:
        Dynamic route pricing payload.
    """

    await asyncio.sleep(random.uniform(0.2, 0.5))
    return {
        "route": f"{origin}-{destination}",
        "price": round(random.uniform(125.0, 450.0), 2),
        "timestamp": time.time(),
    }


async def failing_service() -> Dict[str, Any]:
    """Simulate an async downstream service failure.

    Raises:
        Exception: Always raised after a short delay.
    """

    await asyncio.sleep(random.uniform(0.1, 0.15))
    raise Exception("Service failure")
