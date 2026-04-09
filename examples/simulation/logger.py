"""Simple structured logger for the simulation demo."""

from __future__ import annotations


_ICONS = {
    "HIT": "HIT",
    "MISS": "MISS",
    "SET": "SET",
    "STALE": "STALE",
    "INVALIDATE": "INVALIDATE",
    "SCENARIO": "SCENARIO",
    "SERVICE": "SERVICE",
    "RESULT": "RESULT",
}


def log(event: str, message: str) -> None:
    """Print a structured simulation log line.

    Args:
        event: Short event label.
        message: Message to print without modifying its meaning.
    """

    label = _ICONS.get(event.upper(), event.upper())
    print(f"[{label}] {message}")
