"""UTC monthly aggregation. Integer base-unit sums only — no floating point."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass
class Transfer:
    to_address: str
    amount_raw: int
    timestamp: int   # unix seconds, UTC


@dataclass
class MonthlyCell:
    counterparty_address: str
    year_month: str          # 'YYYY-MM'
    total_raw: int
    tx_count: int


def year_month_utc(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%Y-%m")


def aggregate_monthly(transfers: list[Transfer]) -> list[MonthlyCell]:
    """Group transfers by (counterparty, UTC month). Exact integer sums."""
    totals: dict[tuple[str, str], int] = defaultdict(int)
    counts: dict[tuple[str, str], int] = defaultdict(int)
    for t in transfers:
        key = (t.to_address, year_month_utc(t.timestamp))
        totals[key] += t.amount_raw
        counts[key] += 1
    return [
        MonthlyCell(addr, ym, totals[(addr, ym)], counts[(addr, ym)])
        for (addr, ym) in sorted(totals)
    ]


def raw_to_decimal_str(amount_raw: int, decimals: int) -> str:
    """Convert base units to a human decimal string without float error."""
    sign = "-" if amount_raw < 0 else ""
    s = str(abs(amount_raw)).rjust(decimals + 1, "0")
    whole, frac = s[:-decimals], s[-decimals:]
    frac = frac.rstrip("0")
    return f"{sign}{whole}.{frac}" if frac else f"{sign}{whole}"
