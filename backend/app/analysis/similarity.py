"""Pairwise similarity signals between two wallets.

Three signals, each normalized to [0, 1], combined into a weighted score. See ARCHITECTURE.md
for the rationale (notably: overlap *coefficient*, not Jaccard, to handle rotation asymmetry).

This module is pure (no I/O) and fully unit-testable.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field

from ..config import settings


@dataclass
class WalletContext:
    """Everything similarity needs about one wallet."""
    address: str
    recipients: set[str] = field(default_factory=set)   # R(W): outbound USDT recipients
    funding_sources: set[str] = field(default_factory=set)  # F(W): inbound top-up sources
    outbound_timestamps: list[int] = field(default_factory=list)  # unix seconds, sorted
    outbound_amounts: list[int] = field(default_factory=list)     # base units


def overlap_coefficient(a: set[str], b: set[str]) -> float:
    """|a ∩ b| / min(|a|, |b|). 0 if either set is empty."""
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def _rel_closeness(x: float, y: float) -> float:
    """1 - normalized absolute difference, in [0, 1]. 0 if both zero."""
    m = max(x, y)
    if m == 0:
        return 0.0
    return 1.0 - min(1.0, abs(x - y) / m)


def _median_interval(timestamps: list[int]) -> float:
    if len(timestamps) < 2:
        return 0.0
    ts = sorted(timestamps)
    gaps = [ts[i + 1] - ts[i] for i in range(len(ts) - 1)]
    return float(statistics.median(gaps))


def recipient_overlap(a: WalletContext, b: WalletContext) -> float:
    return overlap_coefficient(a.recipients, b.recipients)


def rhythm_similarity(a: WalletContext, b: WalletContext) -> float:
    interval_sim = _rel_closeness(
        _median_interval(a.outbound_timestamps),
        _median_interval(b.outbound_timestamps),
    )
    amt_a = float(statistics.median(a.outbound_amounts)) if a.outbound_amounts else 0.0
    amt_b = float(statistics.median(b.outbound_amounts)) if b.outbound_amounts else 0.0
    amount_sim = _rel_closeness(amt_a, amt_b)
    return 0.5 * interval_sim + 0.5 * amount_sim


def funding_similarity(a: WalletContext, b: WalletContext) -> float:
    return overlap_coefficient(a.funding_sources, b.funding_sources)


def pair_score(a: WalletContext, b: WalletContext) -> float:
    """Combined similarity in [0, 1].

    Recipient overlap + payment rhythm form the *base* (renormalized to [0, 1]). Shared funding
    is a positive-only *bonus*: its presence raises confidence, but its absence never penalizes.
    Rationale (validated on real data): an entity may fund rotated wallets from different
    sources, so absent funding overlap is weak evidence, not counter-evidence.
    """
    base_w = settings.weight_overlap + settings.weight_rhythm
    base = (
        settings.weight_overlap * recipient_overlap(a, b)
        + settings.weight_rhythm * rhythm_similarity(a, b)
    ) / base_w if base_w else 0.0
    score = base + settings.weight_funding * funding_similarity(a, b)
    return min(1.0, score)
