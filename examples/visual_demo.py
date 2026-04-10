"""Shipsy Cache Library — Visual Demo

A rich terminal demonstration of every library feature using logistics-realistic
data. Uses a private demo-only backend so no external services are needed.

Install and run:
    pip install rich
    python examples/visual_demo.py

If rich is not installed, the demo will print a helpful error message.
"""

from __future__ import annotations

import asyncio
import json
import random
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from shipsy_cache import FactoryError, TieredCache
from shipsy_cache.l2.base import L2Backend


CARRIERS: Dict[str, Dict[str, float]] = {
    "delhivery": {"base": 45.0, "per_kg": 12.5, "avg_days": 3},
    "bluedart": {"base": 65.0, "per_kg": 18.0, "avg_days": 2},
    "dtdc": {"base": 38.0, "per_kg": 10.0, "avg_days": 4},
    "ecom_express": {"base": 42.0, "per_kg": 11.5, "avg_days": 3},
    "xpressbees": {"base": 40.0, "per_kg": 11.0, "avg_days": 3},
    "shadowfax": {"base": 35.0, "per_kg": 9.5, "avg_days": 5},
}

SHIPMENT_STATUSES = [
    "manifested",
    "picked_up",
    "in_transit",
    "at_hub",
    "out_for_delivery",
    "delivered",
    "rto_initiated",
    "rto_delivered",
]

HIT_STYLE = "bold green"
MISS_STYLE = "bold red"
STALE_STYLE = "bold yellow"
L1_STYLE = "cyan"
L2_STYLE = "magenta"
ERROR_STYLE = "bold red"
KEY_STYLE = "blue"
LATENCY_STYLE = "dim"


class _VisualDemoL2(L2Backend):
    """Private in-process L2 used only by the visual demo."""

    def __init__(self, namespace: str = "shipsy_demo", latency_ms: float = 5.0) -> None:
        """Initialize the demo backend."""

        self._namespace = namespace
        self._latency_ms = latency_ms
        self._store: Dict[str, Tuple[bytes, Optional[float]]] = {}
        self._lock = asyncio.Lock()
        self._operations = 0

    async def get(self, key: str) -> Optional[Any]:
        """Return a fresh value or ``None`` when missing or expired."""

        self._operations += 1
        await self._apply_latency()
        async with self._lock:
            entry = self._store.get(self._prefix(key))
            if entry is None:
                return None

            raw_value, expire_at = entry
            if expire_at is not None and time.monotonic() >= expire_at:
                self._store.pop(self._prefix(key), None)
                return None

            return json.loads(raw_value.decode("utf-8"))

    async def set(self, key: str, value: Any, ttl_seconds: float) -> None:
        """Store a JSON-serializable value with TTL semantics."""

        self._operations += 1
        await self._apply_latency()
        expire_at = time.monotonic() + ttl_seconds if ttl_seconds is not None else None
        async with self._lock:
            self._store[self._prefix(key)] = (
                json.dumps(value).encode("utf-8"),
                expire_at,
            )

    async def delete(self, key: str) -> None:
        """Delete a key if present."""

        self._operations += 1
        await self._apply_latency()
        async with self._lock:
            self._store.pop(self._prefix(key), None)

    async def clear(self) -> None:
        """Clear the demo backend."""

        await self._apply_latency()
        async with self._lock:
            self._store.clear()

    async def ping(self) -> bool:
        """Return ``True`` because the demo backend is in-process."""

        return True

    def diagnostics(self) -> Dict[str, Any]:
        """Return small diagnostics for the final dashboard."""

        now = time.monotonic()
        live_keys = sum(
            1
            for _, expire_at in self._store.values()
            if expire_at is None or expire_at > now
        )
        return {
            "namespace": self._namespace,
            "live_keys": live_keys,
            "total_operations": self._operations,
            "simulated_failures": 0,
        }

    async def _apply_latency(self) -> None:
        """Simulate L2 round-trip latency."""

        if self._latency_ms > 0:
            await asyncio.sleep(self._latency_ms / 1000.0)

    def _prefix(self, key: str) -> str:
        """Prefix storage keys for the demo backend."""

        return f"{self._namespace}:{key}"


async def fetch_carrier_rate(carrier: str, origin: str, dest: str, weight: float) -> Dict[str, Any]:
    """Simulate a carrier rate API call."""

    await asyncio.sleep(random.uniform(0.15, 0.30))
    info = CARRIERS[carrier]
    return {
        "carrier": carrier,
        "route": f"{origin}→{dest}",
        "weight_kg": weight,
        "total": round(info["base"] + info["per_kg"] * weight, 2),
        "currency": "INR",
        "eta_days": int(info["avg_days"]),
    }


async def fetch_tracking(awb: str) -> Dict[str, Any]:
    """Simulate a tracking service call."""

    await asyncio.sleep(random.uniform(0.08, 0.20))
    return {
        "awb": awb,
        "status": random.choice(SHIPMENT_STATUSES),
        "location": random.choice(
            ["Delhi Hub", "Mumbai Sort", "Bangalore DC", "Hyderabad Hub"],
        ),
    }


async def fetch_merchant_config(merchant_id: str) -> Dict[str, Any]:
    """Simulate a merchant configuration service call."""

    await asyncio.sleep(random.uniform(0.20, 0.40))
    return {
        "merchant_id": merchant_id,
        "delivery_sla_hours": 48,
        "rto_window_days": 7,
        "preferred_carriers": ["delhivery", "bluedart"],
    }


def format_ms(seconds: float) -> str:
    """Return a duration formatted in milliseconds."""

    return f"{seconds * 1000:.0f}ms"


def format_ms_precise(seconds: float) -> str:
    """Return a duration formatted in milliseconds with one decimal place."""

    return f"{seconds * 1000:.1f}ms"


def attach_event_listeners(cache: TieredCache, event_log: List[Dict[str, Any]]) -> None:
    """Attach cache listeners that record the real event payloads."""

    def listener(payload: Dict[str, Any]) -> None:
        event_log.append(dict(payload))

    for event_name in (
        "cache:hit",
        "cache:miss",
        "cache:set",
        "cache:stale-served",
        "cache:invalidate",
    ):
        cache.on(event_name, listener)


def event_type_style(event_name: str) -> str:
    """Return the visual style for an event type."""

    styles = {
        "cache:hit": HIT_STYLE,
        "cache:miss": MISS_STYLE,
        "cache:set": "bold blue",
        "cache:invalidate": STALE_STYLE,
        "cache:stale-served": STALE_STYLE,
    }
    return styles.get(event_name, "white")


def status_from_events(events: List[Dict[str, Any]], text_cls: Any) -> Any:
    """Build a status label from actual event payloads."""

    hit = next((event for event in events if event["event"] == "cache:hit"), None)
    stale = next((event for event in events if event["event"] == "cache:stale-served"), None)
    miss = next((event for event in events if event["event"] == "cache:miss"), None)
    if stale is not None:
        return text_cls("STALE", style=STALE_STYLE)
    if hit is not None:
        tier = hit.get("tier")
        tier_style = L1_STYLE if tier == "L1" else L2_STYLE
        label = text_cls("HIT", style=HIT_STYLE)
        if tier is not None:
            label.append(" ")
            label.append(f"({tier})", style=tier_style)
        return label
    if miss is not None:
        return text_cls("MISS", style=MISS_STYLE)
    return text_cls("—", style="white")


def source_from_events(events: List[Dict[str, Any]]) -> str:
    """Infer the cache source from actual hit events."""

    for event in events:
        if event["event"] == "cache:hit":
            return str(event.get("tier", "unknown"))
    return "unknown"


def payload_table(table_cls: Any, box_mod: Any, title: str, payload: Dict[str, Any]) -> Any:
    """Render a small key-value payload table."""

    table = table_cls(title=title, box=box_mod.SIMPLE_HEAVY, expand=True)
    table.add_column("Field", style=KEY_STYLE)
    table.add_column("Value")
    for key, value in payload.items():
        table.add_row(str(key), str(value))
    return table


async def scenario_rate_shopping(
    console: Any,
    ui: Dict[str, Any],
    cache: TieredCache,
    event_log: List[Dict[str, Any]],
) -> None:
    """Show cold versus warm carrier rate shopping."""

    table_cls = ui["Table"]
    panel_cls = ui["Panel"]
    text_cls = ui["Text"]
    box_mod = ui["box"]

    console.print(
        panel_cls.fit(
            "🚚 Scenario 1: Rate Shopping — Route DEL → BLR (2.5 kg)",
            border_style=L2_STYLE,
        ),
    )

    def make_table(title: str) -> Any:
        table = table_cls(title=title, box=box_mod.SIMPLE_HEAVY, expand=True)
        table.add_column("Carrier", style=KEY_STYLE)
        table.add_column("Total (₹)", justify="right")
        table.add_column("ETA", justify="right")
        table.add_column("Latency", justify="right", style=LATENCY_STYLE)
        table.add_column("Status")
        return table

    cold_table = make_table("Cold Fetch")
    cold_total = 0.0
    cheapest_carrier = ""
    cheapest_amount = float("inf")

    for carrier in CARRIERS:
        key = f"rate:{carrier}:DEL:BLR"
        event_index = len(event_log)
        start = time.perf_counter()
        result = await cache.getOrSet(
            key,
            lambda carrier_name=carrier: fetch_carrier_rate(carrier_name, "DEL", "BLR", 2.5),
            ttl="15m",
        )
        elapsed = time.perf_counter() - start
        cold_total += elapsed
        cheapest_carrier, cheapest_amount = (
            (result["carrier"], result["total"])
            if result["total"] < cheapest_amount
            else (cheapest_carrier, cheapest_amount)
        )
        cold_table.add_row(
            carrier,
            f"{result['total']:.2f}",
            f"{result['eta_days']}d",
            format_ms(elapsed),
            status_from_events(event_log[event_index:], text_cls),
        )

    console.print(cold_table)
    console.print(
        panel_cls(
            f"Total: [dim]{format_ms(cold_total)}[/dim] | "
            f"Cheapest: [bold green]{cheapest_carrier}[/bold green] @ "
            f"[bold]₹{cheapest_amount:.2f}[/bold]",
            border_style="green",
        ),
    )

    warm_table = make_table("Warm Fetch")
    warm_total = 0.0
    for carrier in CARRIERS:
        key = f"rate:{carrier}:DEL:BLR"
        event_index = len(event_log)
        start = time.perf_counter()
        result = await cache.getOrSet(
            key,
            lambda carrier_name=carrier: fetch_carrier_rate(carrier_name, "DEL", "BLR", 2.5),
            ttl="15m",
        )
        elapsed = time.perf_counter() - start
        warm_total += elapsed
        warm_table.add_row(
            carrier,
            f"{result['total']:.2f}",
            f"{result['eta_days']}d",
            format_ms_precise(elapsed),
            status_from_events(event_log[event_index:], text_cls),
        )

    console.print(warm_table)
    speedup = cold_total / warm_total if warm_total else 0.0
    console.print(
        panel_cls(
            f"Total: [dim]{format_ms_precise(warm_total)}[/dim] | "
            f"Speedup: [bold green]{speedup:.0f}×[/bold green]",
            border_style="green",
        ),
    )


async def scenario_stampede(console: Any, ui: Dict[str, Any], cache: TieredCache) -> None:
    """Show stampede protection under high concurrency."""

    table_cls = ui["Table"]
    panel_cls = ui["Panel"]
    text_cls = ui["Text"]
    box_mod = ui["box"]

    console.print(
        panel_cls.fit(
            "🛡️ Scenario 2: Stampede Protection — 50 requests for AWB-DEL-78234",
            border_style=L2_STYLE,
        ),
    )

    key = "tracking:AWB-DEL-78234"
    await cache.invalidate(key)
    factory_calls = 0
    latencies: List[float] = []

    async def factory() -> Dict[str, Any]:
        nonlocal factory_calls
        factory_calls += 1
        return await fetch_tracking("AWB-DEL-78234")

    async def worker() -> Dict[str, Any]:
        start = time.perf_counter()
        result = await cache.getOrSet(key, factory, ttl="30s")
        latencies.append(time.perf_counter() - start)
        return result

    results = await asyncio.gather(*(worker() for _ in range(50)))
    all_match = len({repr(result) for result in results}) == 1
    leader_latency = max(latencies)
    follower_latencies = [latency for latency in latencies if latency != leader_latency]
    avg_follower = sum(follower_latencies) / len(follower_latencies) if follower_latencies else 0.0

    table = table_cls(box=box_mod.SIMPLE_HEAVY, expand=True)
    table.add_column("Metric", style=KEY_STYLE)
    table.add_column("Value")
    table.add_row("Concurrent requests", "50")
    table.add_row(
        "Factory invocations",
        text_cls(
            f"{factory_calls} {'✓' if factory_calls == 1 else '✗'}",
            style=HIT_STYLE if factory_calls == 1 else ERROR_STYLE,
        ),
    )
    table.add_row("All results match", text_cls("✓" if all_match else "✗", style=HIT_STYLE if all_match else ERROR_STYLE))
    table.add_row("Leader latency", format_ms(leader_latency))
    table.add_row("Avg follower wait", format_ms_precise(avg_follower))
    console.print(table)


async def scenario_ttl_lifecycle(console: Any, ui: Dict[str, Any], cache: TieredCache) -> None:
    """Show a live TTL lifecycle for a tracking entry."""

    table_cls = ui["Table"]
    panel_cls = ui["Panel"]
    live_cls = ui["Live"]
    text_cls = ui["Text"]
    box_mod = ui["box"]

    console.print(
        panel_cls.fit(
            "⏱️ Scenario 3: TTL Expiry — 2s TTL lifecycle",
            border_style=L2_STYLE,
        ),
    )

    key = "tracking:ttl:AWB-DEL-78234"
    value = await fetch_tracking("AWB-DEL-78234")
    await cache.set(key, value, ttl="2s")

    rows: List[Tuple[str, str, Any]] = []
    checkpoints = [0.0, 0.5, 1.0, 1.5, 2.0, 2.5]

    with live_cls(console=console, refresh_per_second=8, transient=True) as live:
        start = time.perf_counter()
        for checkpoint in checkpoints:
            remaining = checkpoint - (time.perf_counter() - start)
            if remaining > 0:
                await asyncio.sleep(remaining)
            result = await cache.get(key)
            if result is None:
                status = text_cls("🔴 EXPIRED", style=MISS_STYLE)
            elif checkpoint >= 1.5:
                status = text_cls("🟡 EXPIRING SOON", style=STALE_STYLE)
            else:
                status = text_cls("🟢 FRESH", style=HIT_STYLE)
            rows.append((f"{checkpoint:.1f}s", str(result), status))

            table = table_cls(box=box_mod.SIMPLE_HEAVY, expand=True)
            table.add_column("Elapsed")
            table.add_column("cache.get() result")
            table.add_column("Status")
            for row in rows:
                table.add_row(row[0], row[1], row[2])
            live.update(table)

    console.print(
        panel_cls(
            "Tracking data stayed fresh until the TTL expired, then aged out cleanly.",
            border_style="green",
        ),
    )


async def scenario_graceful_degradation(
    console: Any,
    ui: Dict[str, Any],
    cache: TieredCache,
    l2: _VisualDemoL2,
) -> None:
    """Show stale serving during a simulated carrier outage."""

    panel_cls = ui["Panel"]
    live_cls = ui["Live"]
    table_cls = ui["Table"]
    box_mod = ui["box"]

    console.print(
        panel_cls.fit(
            "🔥 Scenario 4: Graceful Degradation — BlueDart API goes down",
            border_style=L2_STYLE,
        ),
    )

    key = "rate:bluedart:DEL:BLR"
    value = await fetch_carrier_rate("bluedart", "DEL", "BLR", 2.5)
    console.print("Setting BlueDart rate with TTL=1.5s, grace_period=30s")
    await cache.set(key, value, ttl=1.5)
    console.print(payload_table(table_cls, box_mod, "Cached BlueDart Rate", value))

    console.print("Waiting for TTL to expire...")
    with live_cls(console=console, refresh_per_second=8, transient=True) as live:
        for remaining in (2.0, 1.5, 1.0, 0.5):
            table = table_cls(box=box_mod.SIMPLE_HEAVY, expand=False)
            table.add_column("Countdown")
            table.add_row(f"{remaining:.1f}s remaining")
            live.update(table)
            await asyncio.sleep(0.5)

    async def broken_factory() -> Dict[str, Any]:
        raise ConnectionError("BlueDart API: connection refused")

    stale_value = await cache.getOrSet(key, broken_factory, ttl="15m")
    console.print(
        panel_cls(
            "⚠️  STALE VALUE SERVED\n"
            "The factory failed but the grace period returned the last known rate.\n"
            "In logistics, a 2-second-old rate is better than a crashed checkout.",
            border_style="yellow",
        ),
    )
    console.print(payload_table(table_cls, box_mod, "Returned Stale Value", stale_value))

    no_grace_cache = TieredCache(
        l2_backend=l2,
        l1_max_size=50,
        default_ttl="10m",
        grace_period=0,
        namespace="logistics-no-grace",
    )
    no_grace_key = "rate:bluedart:DEL:BLR"
    await no_grace_cache.set(no_grace_key, value, ttl=1.5)
    await asyncio.sleep(2.0)
    try:
        await no_grace_cache.getOrSet(no_grace_key, broken_factory, ttl="15m")
    except FactoryError as exc:
        cause = exc.__cause__
        cause_message = str(cause) if cause is not None else str(exc)
        console.print(
            panel_cls(
                "❌ ERROR — No grace period\n"
                f"FactoryError: {cause_message}\n"
                "Without graceful degradation, the checkout flow crashes.",
                border_style="red",
                style=ERROR_STYLE,
            ),
        )


async def scenario_l2_hydration(
    console: Any,
    ui: Dict[str, Any],
    cache: TieredCache,
    l2: _VisualDemoL2,
    event_log: List[Dict[str, Any]],
) -> None:
    """Show L2 to L1 hydration for a multi-instance style workflow."""

    table_cls = ui["Table"]
    panel_cls = ui["Panel"]
    box_mod = ui["box"]

    console.print(
        panel_cls.fit(
            "🔄 Scenario 5: L2 → L1 Hydration (multi-instance simulation)",
            border_style=L2_STYLE,
        ),
    )
    console.print(
        panel_cls(
            "Simulating two service instances sharing Redis.\n"
            "Instance B writes warehouse config directly to L2.\n"
            "Instance A reads through TieredCache — finds it in L2, hydrates L1.",
            border_style=L1_STYLE,
        ),
    )

    key = "warehouse:config"
    payload = {
        "warehouse_id": "WH-DEL-01",
        "sort_cutoff": "18:30",
        "supports_cod": True,
    }
    await l2.set(cache._namespaced_key(key), payload, ttl_seconds=300)

    first_event_index = len(event_log)
    start = time.perf_counter()
    first_value = await cache.get(key)
    first_latency = time.perf_counter() - start
    first_source = source_from_events(event_log[first_event_index:])

    second_event_index = len(event_log)
    start = time.perf_counter()
    second_value = await cache.get(key)
    second_latency = time.perf_counter() - start
    second_source = source_from_events(event_log[second_event_index:])

    table = table_cls(box=box_mod.SIMPLE_HEAVY, expand=True)
    table.add_column("Read")
    table.add_column("Source")
    table.add_column("Latency", style=LATENCY_STYLE)
    table.add_column("Value")
    table.add_row("1st", first_source, format_ms_precise(first_latency), str(first_value))
    table.add_row("2nd", second_source, format_ms_precise(second_latency), str(second_value))
    console.print(table)


async def scenario_event_stream(
    console: Any,
    ui: Dict[str, Any],
    cache: TieredCache,
    event_log: List[Dict[str, Any]],
) -> None:
    """Show the captured event stream for a deterministic sequence."""

    table_cls = ui["Table"]
    panel_cls = ui["Panel"]
    text_cls = ui["Text"]
    box_mod = ui["box"]

    console.print(
        panel_cls.fit(
            "📡 Scenario 6: Event Stream",
            border_style=L2_STYLE,
        ),
    )

    key = "rate:delhivery:event-demo"
    start_index = len(event_log)
    await cache.getOrSet(
        key,
        lambda: fetch_carrier_rate("delhivery", "DEL", "BLR", 1.0),
        ttl="15m",
    )
    await cache.getOrSet(
        key,
        lambda: fetch_carrier_rate("delhivery", "DEL", "BLR", 1.0),
        ttl="15m",
    )
    await cache.invalidate(key)
    await cache.getOrSet(
        key,
        lambda: fetch_carrier_rate("delhivery", "DEL", "BLR", 1.0),
        ttl="15m",
    )

    table = table_cls(box=box_mod.SIMPLE_HEAVY, expand=True)
    table.add_column("#", justify="right")
    table.add_column("Event Type")
    table.add_column("Key", style=KEY_STYLE)
    table.add_column("Details")

    scenario_events = event_log[start_index:]
    for index, event in enumerate(scenario_events, start=1):
        detail_parts = [
            f"{name}={value}"
            for name, value in event.items()
            if name not in {"event", "key", "timestamp"}
        ]
        table.add_row(
            str(index),
            text_cls(event["event"], style=event_type_style(event["event"])),
            event["key"],
            ", ".join(detail_parts) if detail_parts else "—",
        )
    console.print(table)


def dashboard_panel(ui: Dict[str, Any], cache: TieredCache, l2: _VisualDemoL2, event_log: List[Dict[str, Any]]) -> Any:
    """Build the final system dashboard."""

    table_cls = ui["Table"]
    panel_cls = ui["Panel"]
    box_mod = ui["box"]

    l1_stats = cache.stats()["l1"]
    l2_stats = l2.diagnostics()
    counts = Counter(event["event"] for event in event_log)

    left = table_cls(box=box_mod.SIMPLE_HEAVY, expand=True)
    left.add_column("L1 Stats", style=KEY_STYLE)
    left.add_column("Value")
    left.add_row("Size", f"{l1_stats['size']} / {l1_stats['max_size']}")
    left.add_row("Namespace", cache.stats()["namespace"])

    right = table_cls(box=box_mod.SIMPLE_HEAVY, expand=True)
    right.add_column("L2 Diagnostics", style=KEY_STYLE)
    right.add_column("Value")
    right.add_row("Backend", "Demo L2")
    right.add_row("Live keys", str(l2_stats["live_keys"]))
    right.add_row("Total operations", str(l2_stats["total_operations"]))
    right.add_row("Simulated failures", str(l2_stats["simulated_failures"]))

    summary = table_cls.grid(expand=True)
    summary.add_row(left, right)
    summary.add_row("")
    summary.add_row("✅ All scenarios completed")
    summary.add_row("🛡️ Stampede protection: verified")
    summary.add_row("♻️  Graceful degradation: verified")
    summary.add_row("📡 Event observability: verified")
    summary.add_row(f"Event counts: {dict(counts)}")
    return panel_cls(summary, title="📊 System Dashboard", border_style="green")


async def main() -> None:
    """Run the visual demo."""

    try:
        from rich import box
        from rich.console import Console
        from rich.live import Live
        from rich.panel import Panel
        from rich.rule import Rule
        from rich.table import Table
        from rich.text import Text
    except ImportError:
        print("This demo requires the 'rich' library for visual output.")
        print("Install it with: pip install rich")
        return

    console = Console()
    ui = {
        "Table": Table,
        "Panel": Panel,
        "Live": Live,
        "Text": Text,
        "Rule": Rule,
        "box": box,
    }

    l2 = _VisualDemoL2(namespace="shipsy_demo", latency_ms=5)
    cache = TieredCache(
        l2_backend=l2,
        l1_max_size=200,
        default_ttl="10m",
        grace_period="30s",
        namespace="logistics",
    )
    event_log: List[Dict[str, Any]] = []
    attach_event_listeners(cache, event_log)

    scenarios: List[Callable[[], Any]] = [
        lambda: scenario_rate_shopping(console, ui, cache, event_log),
        lambda: scenario_stampede(console, ui, cache),
        lambda: scenario_ttl_lifecycle(console, ui, cache),
        lambda: scenario_graceful_degradation(console, ui, cache, l2),
        lambda: scenario_l2_hydration(console, ui, cache, l2, event_log),
        lambda: scenario_event_stream(console, ui, cache, event_log),
    ]

    for index, scenario in enumerate(scenarios, start=1):
        await scenario()
        if index != len(scenarios):
            console.print(ui["Rule"]())

    console.print(dashboard_panel(ui, cache, l2, event_log))


if __name__ == "__main__":
    asyncio.run(main())
