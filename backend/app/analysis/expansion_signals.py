"""Pure scoring for entity expansion: pay-cycle fingerprint, recipient/payer scores, tiers.

No I/O — fully unit-testable, like similarity.py.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone


def pay_cycle_fingerprint(timestamps: list[int]) -> set[int]:
    """Days-of-month where confirmed payments cluster (the entity's fixed pay dates)."""
    days = [datetime.fromtimestamp(t, tz=timezone.utc).day for t in timestamps]
    if not days:
        return set()
    counts = Counter(days)
    peak = max(counts.values())
    threshold = max(2, peak * 0.5)
    return {d for d, n in counts.items() if n >= threshold}


def aligns_with_cycle(timestamp: int, fingerprint: set[int], tolerance_days: int) -> bool:
    if not fingerprint:
        return False
    day = datetime.fromtimestamp(timestamp, tz=timezone.utc).day
    return any(abs(day - peak) <= tolerance_days for peak in fingerprint)
