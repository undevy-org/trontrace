"""Fixed-amount recurring-recipient ranking (pure, no I/O).

Ranks recipients by how consistently they receive the same monthly amount, and flags likely
wallet-change pairs. Operates on monthly series read elsewhere; this module stays pure.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass

from .expansion_signals import amount_consistency


@dataclass
class ConsistentRow:
    address: str
    median_monthly: int
    months_paid: int
    consistency: float


def consistent_rows(
    timelines: dict[str, list[tuple[str, int]]],
    *,
    band_low: int,
    band_high: int,
    min_consistency: float,
    min_months: int,
) -> list[ConsistentRow]:
    """Keep recipients with a stable monthly amount in band; sort by amount descending."""
    out: list[ConsistentRow] = []
    for address, series in timelines.items():
        amounts = [amt for _ym, amt in series]
        if len(amounts) < min_months:
            continue
        median = int(statistics.median(amounts))
        if not (band_low <= median <= band_high):
            continue
        cons = amount_consistency(amounts)
        if cons < min_consistency:
            continue
        out.append(ConsistentRow(address, median, len(amounts), cons))
    out.sort(key=lambda r: -r.median_monthly)
    return out
