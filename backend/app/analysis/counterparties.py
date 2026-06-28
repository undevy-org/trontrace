"""Derive counterparties from the primary-payer cluster.

Counterparties = distinct recipients of the primary-payer cluster, minus the anchor, minus
exchange-flagged recipients (those are surfaced separately as "needs manual check").
"""
from __future__ import annotations


def derive_counterparties(
    primary_payer_recipients: set[str],
    anchor: str,
    exchange_addresses: set[str],
    payers: set[str] = frozenset(),
) -> tuple[set[str], set[str]]:
    """Return (counterparties, needs_manual_check).

    Excludes the anchor and the primary-payer wallets themselves (`payers`) — a payer that
    self-transfers must not be counted as its own counterparty.

    needs_manual_check = recipients that are exchange-flagged (exclude from income totals,
    but show with an explorer link).
    """
    pool = primary_payer_recipients - {anchor} - set(payers)
    needs_check = pool & exchange_addresses
    counterparties = pool - needs_check
    return counterparties, needs_check
