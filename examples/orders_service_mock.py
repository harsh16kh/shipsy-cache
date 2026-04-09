"""Mock Orders Service demonstrating cache integration in a logistics context.
Simulates Shipsy TMS use case: caching carrier rate lookups.
Shows DB load reduction with and without cache.
Run: python examples/orders_service_mock.py
"""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shipsy_cache import TieredCache


@dataclass
class MockCarrierRateRecord:
    """Simple value object representing a carrier rate lookup."""

    carrier_id: str
    amount: float
    currency: str


class OrdersService:
    """Mock service that wraps an expensive carrier-rate data source with caching."""

    def __init__(self) -> None:
        """Initialize service state and cache."""

        self.db_calls = 0
        self.cache = TieredCache(default_ttl=30, grace_period=10, namespace="orders-service")

    async def _fetch_rates_from_db(self, carrier_id: str) -> Dict[str, str]:
        """Simulate a slow database lookup for carrier rates."""

        self.db_calls += 1
        print(f"DB query executed for carrier_id={carrier_id}")
        await asyncio.sleep(0.15)
        record = MockCarrierRateRecord(carrier_id=carrier_id, amount=124.50, currency="INR")
        return {
            "carrier_id": record.carrier_id,
            "amount": f"{record.amount:.2f}",
            "currency": record.currency,
        }

    async def get_carrier_rates(self, carrier_id: str) -> Dict[str, str]:
        """Return carrier rates using the cache-aside pattern."""

        cache_key = f"carrier-rates:{carrier_id}"
        return await self.cache.getOrSet(
            cache_key,
            lambda: self._fetch_rates_from_db(carrier_id),
            ttl=30,
        )


async def main() -> None:
    """Demonstrate repeated carrier lookups collapsing to a single DB call."""

    service = OrdersService()
    carrier_id = "BLR-DEL-EXPRESS"

    print("Issuing 10 requests for the same carrier_id...")
    results: List[Dict[str, str]] = await asyncio.gather(
        *(service.get_carrier_rates(carrier_id) for _ in range(10)),
    )

    print("\nReturned payloads:")
    for index, payload in enumerate(results, start=1):
        print(f"Request {index}: {payload}")

    print(f"\nDatabase was called {service.db_calls} time(s).")
    print("Expected: 1 database call because getOrSet() prevents stampedes.")


if __name__ == "__main__":
    asyncio.run(main())
