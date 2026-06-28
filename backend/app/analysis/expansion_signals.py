"""Pure scoring for entity expansion: pay-cycle fingerprint, recipient/payer scores, tiers.

No I/O — fully unit-testable, like similarity.py.
"""
from __future__ import annotations

import statistics
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone

from ..config import settings


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


def _recurrence(months_paid: int, months_span: int) -> float:
    if months_span <= 0:
        return 0.0
    return min(1.0, months_paid / months_span)


def _amount_stability(amounts: list[int]) -> float:
    """1 - coefficient of variation, clamped to [0,1]. Stable amounts -> near 1."""
    if len(amounts) < 2:
        return 0.0
    mean = statistics.mean(amounts)
    if mean == 0:
        return 0.0
    cv = statistics.pstdev(amounts) / mean
    return max(0.0, 1.0 - cv)


@dataclass
class RecipientFeatures:
    n_payers: int
    months_paid: int
    months_span: int
    aligned_fraction: float
    amounts: list[int] = field(default_factory=list)
    distinct_senders: int = 0


def recipient_score(f: RecipientFeatures) -> float:
    corec = min(1.0, f.n_payers / max(1, settings.corecipient_min_k))
    rec = _recurrence(f.months_paid, f.months_span)
    align = max(0.0, min(1.0, f.aligned_fraction))
    stab = _amount_stability(f.amounts)
    fanin = 0.0 if f.distinct_senders > settings.recipient_fanin_cap else 1.0
    score = (settings.w_rec_corecipient * corec
             + settings.w_rec_recurrence * rec
             + settings.w_rec_paycycle * align
             + settings.w_rec_stability * stab
             + settings.w_rec_fanin * fanin)
    return min(1.0, score)


def tier(conf: float) -> str:
    if conf >= settings.expand_tier_high:
        return "high"
    if conf >= settings.expand_tier_med:
        return "med"
    return "low"
