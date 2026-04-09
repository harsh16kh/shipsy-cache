"""TTL parsing helpers."""

from __future__ import annotations

import re
from typing import Union


TTLValue = Union[int, float, str]

_TTL_PATTERN = re.compile(r"^\s*(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>[smhd])\s*$", re.IGNORECASE)
_UNIT_MULTIPLIERS = {
    "s": 1.0,
    "m": 60.0,
    "h": 3600.0,
    "d": 86400.0,
}


def parse_ttl(ttl: TTLValue) -> float:
    """Parse a TTL value into seconds.

    Args:
        ttl: TTL as numeric seconds or a compact string such as ``"30s"``,
            ``"5m"``, ``"2h"``, or ``"1d"``.

    Returns:
        The TTL value in seconds as a float.

    Raises:
        ValueError: If the TTL format is unsupported or negative.
    """

    if isinstance(ttl, (int, float)) and not isinstance(ttl, bool):
        ttl_seconds = float(ttl)
        if ttl_seconds < 0:
            raise ValueError("TTL must be non-negative.")
        return ttl_seconds

    if isinstance(ttl, str):
        match = _TTL_PATTERN.match(ttl)
        if not match:
            raise ValueError(f"Invalid TTL string: {ttl!r}")
        value = float(match.group("value"))
        unit = match.group("unit").lower()
        return value * _UNIT_MULTIPLIERS[unit]

    raise ValueError(f"Unsupported TTL type: {type(ttl)!r}")
