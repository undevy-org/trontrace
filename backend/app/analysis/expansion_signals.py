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


def _recurrence(months_paid: int) -> float:
    """Reward absolute tenure: full credit at recurrence_target_months paid months."""
    return min(1.0, months_paid / settings.recurrence_target_months)


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
    aligned_fraction: float
    amounts: list[int] = field(default_factory=list)
    distinct_senders: int = 0


def recipient_score(f: RecipientFeatures) -> float:
    corec = min(1.0, f.n_payers / max(1, settings.corecipient_min_k))
    rec = _recurrence(f.months_paid)
    align = max(0.0, min(1.0, f.aligned_fraction))
    stab = _amount_stability(f.amounts)
    fanin = 0.0 if f.distinct_senders > settings.recipient_fanin_cap else 1.0
    score = (settings.w_rec_corecipient * corec
             + settings.w_rec_recurrence * rec
             + settings.w_rec_paycycle * align
             + settings.w_rec_stability * stab
             + settings.w_rec_fanin * fanin)
    # Hard gate: a recipient paid in fewer than recurrence_min_months distinct months is
    # not recurring — clamp below Med/High so it never joins the expansion cohort.
    if f.months_paid < settings.recurrence_min_months:
        return min(score, settings.expand_tier_med - 1e-6)
    return min(1.0, score)


def tier(conf: float) -> str:
    if conf >= settings.expand_tier_high:
        return "high"
    if conf >= settings.expand_tier_med:
        return "med"
    return "low"


@dataclass
class PayerFeatures:
    overlap_with_cohort: float
    n_known_recipients_paid: int
    aligned_fraction: float
    is_exchange: bool = False


def payer_score(f: PayerFeatures) -> float:
    """Hard gate: not an exchange, and co-pays >= K known recipients. Else 0."""
    if f.is_exchange or f.n_known_recipients_paid < settings.corecipient_min_k:
        return 0.0
    corrob = min(1.0, f.n_known_recipients_paid / max(1, settings.corecipient_min_k * 2))
    score = (settings.w_pay_overlap * max(0.0, min(1.0, f.overlap_with_cohort))
             + settings.w_pay_paycycle * max(0.0, min(1.0, f.aligned_fraction))
             + settings.w_pay_corroboration * corrob)
    return min(1.0, score)
