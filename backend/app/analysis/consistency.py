"""Fixed-amount recurring-recipient ranking (pure, no I/O).

Ranks recipients by how consistently they receive the same monthly amount, and flags likely
wallet-change pairs. Operates on monthly series read elsewhere; this module stays pure.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass

from .expansion_signals import amount_consistency
from ..config import settings


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


def _months_between(end_ym: str, start_ym: str) -> int:
    ey, em = (int(x) for x in end_ym.split("-"))
    sy, sm = (int(x) for x in start_ym.split("-"))
    return (sy - ey) * 12 + (sm - em)


def wallet_change_hints(
    rows: list[ConsistentRow], timelines: dict[str, list[tuple[str, int]]]
) -> list[tuple[str, str, str]]:
    """Flag (earlier, later, reason) pairs with ~equal amount and adjacent, non-overlapping months."""
    by_addr = {r.address: r for r in rows}
    ranges = {a: (min(ym for ym, _ in s), max(ym for ym, _ in s)) for a, s in timelines.items()}
    addrs = [r.address for r in rows]
    hints: list[tuple[str, str, str]] = []
    for a in addrs:
        for b in addrs:
            if a == b or a not in ranges or b not in ranges:
                continue
            ma, mb = by_addr[a].median_monthly, by_addr[b].median_monthly
            if max(ma, mb) == 0 or abs(ma - mb) / max(ma, mb) > settings.consistent_change_amount_tol:
                continue
            a_hi, b_lo = ranges[a][1], ranges[b][0]
            step = _months_between(a_hi, b_lo)        # >=1 means b starts after a ends
            if step >= 1 and (step - 1) <= settings.consistent_change_max_gap_months:
                hints.append((a, b, "same amount, adjacent months"))
    return hints
