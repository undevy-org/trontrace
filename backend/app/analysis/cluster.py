"""Agglomerative average-linkage clustering + primary-payer selection.

Average-linkage (not single-linkage / connected components) is deliberate: it bounds
intra-cluster cohesion and resists weak-chain blow-ups where A~B, B~C but A≁C still merge.

Pure logic, no I/O.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..config import settings
from .similarity import WalletContext, pair_score


@dataclass
class Cluster:
    members: list[str]
    confidence: float = 0.0


def _avg_linkage(
    c1: list[str], c2: list[str], scores: dict[tuple[str, str], float]
) -> float:
    total = 0.0
    n = 0
    for a in c1:
        for b in c2:
            total += scores[(a, b)] if (a, b) in scores else scores[(b, a)]
            n += 1
    return total / n if n else 0.0


def cluster_wallets(contexts: list[WalletContext]) -> list[Cluster]:
    """Average-linkage agglomerative clustering with threshold settings.score_threshold."""
    addrs = [c.address for c in contexts]
    by_addr = {c.address: c for c in contexts}

    # Precompute all pairwise scores once.
    scores: dict[tuple[str, str], float] = {}
    for i in range(len(addrs)):
        for j in range(i + 1, len(addrs)):
            a, b = addrs[i], addrs[j]
            scores[(a, b)] = pair_score(by_addr[a], by_addr[b])

    clusters: list[list[str]] = [[a] for a in addrs]
    tau = settings.score_threshold

    while True:
        best = (-1.0, -1, -1)
        for i in range(len(clusters)):
            for j in range(i + 1, len(clusters)):
                s = _avg_linkage(clusters[i], clusters[j], scores)
                if s > best[0]:
                    best = (s, i, j)
        if best[0] <= tau or best[1] < 0:
            break
        _, i, j = best
        clusters[i].extend(clusters[j])
        clusters.pop(j)

    return [Cluster(members=m, confidence=_confidence(m, scores)) for m in clusters]


def _confidence(members: list[str], scores: dict[tuple[str, str], float]) -> float:
    if len(members) < 2:
        return 0.0
    vals = []
    for i in range(len(members)):
        for j in range(i + 1, len(members)):
            a, b = members[i], members[j]
            vals.append(scores[(a, b)] if (a, b) in scores else scores[(b, a)])
    avg = sum(vals) / len(vals)
    return max(0.0, min(1.0, avg))


def select_primary_payer(
    clusters: list[Cluster], paid_to_anchor_recent: dict[str, int]
) -> Cluster | None:
    """Pick the cluster paying the anchor the most within the recent window.

    paid_to_anchor_recent: address -> base-unit total paid to the anchor in the window.
    Selection is by *payment volume*, not cluster size, so a stray exchange cluster cannot win.
    """
    if not clusters:
        return None
    return max(
        clusters,
        key=lambda c: sum(paid_to_anchor_recent.get(m, 0) for m in c.members),
    )
