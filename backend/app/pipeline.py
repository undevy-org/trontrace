"""Analysis pipeline (Pipeline phases 1-7).

Orchestrates fetch -> persist -> classify -> cluster -> aggregate, driven by an injected
TronGridClient (so it is testable without the network). Pure decision logic lives in
app/analysis/*; this module wires it to storage and the data provider.

Progress + the last-fetched cursor are checkpointed in the `progress` table so an interrupted
run can resume without re-fetching (see worker.py).
"""
from __future__ import annotations

from . import store
from .analysis.classify import is_exchange, known_exchanges
from .analysis.cluster import cluster_wallets, select_primary_payer
from .analysis.counterparties import derive_counterparties
from .analysis.monthly import Transfer, aggregate_monthly
from .analysis.similarity import WalletContext
from .config import settings
from .trongrid import TronGridClient


async def run_analysis(anchor: str, client: TronGridClient) -> None:
    store.set_progress(anchor=anchor, phase="inbound", percent=0)
    store.upsert_wallet(anchor, role="anchor")

    # --- Phase 1: inbound — who paid the anchor ---
    inbound = await client.fetch_transfers(anchor, direction="in")
    store.insert_transactions(inbound.records)
    candidates = sorted(store.get_candidates(anchor))

    # --- Phase 2-3: candidate context + exchange gate ---
    store.set_progress(phase="candidate_ctx", percent=10)
    contexts: list[WalletContext] = []
    exchange_addrs: set[str] = set()
    blocklist = known_exchanges()

    for i, cand in enumerate(candidates):
        store.set_progress(last_candidate=cand,
                           percent=10 + int(50 * (i + 1) / max(1, len(candidates))))

        if cand in blocklist:
            store.set_role(cand, "exchange")
            exchange_addrs.add(cand)
            continue

        out = await client.fetch_transfers(
            cand, direction="out", max_records=settings.candidate_tx_cap
        )
        store.insert_transactions(out.records)
        recipients = store.get_recipients(cand) - {anchor}

        if is_exchange(cand, distinct_recipients=len(recipients), tx_cap_hit=out.cap_hit):
            store.set_role(cand, "exchange")
            exchange_addrs.add(cand)
            continue

        funding = await client.fetch_transfers(
            cand, direction="in", max_records=settings.funding_fetch_cap
        )
        store.insert_transactions(funding.records)

        ts, amts = store.get_outbound_series(cand)
        contexts.append(
            WalletContext(
                address=cand,
                recipients=recipients,
                funding_sources=store.get_funding_sources(cand) - {anchor},
                outbound_timestamps=ts,
                outbound_amounts=amts,
            )
        )

    # --- Phase 4-5: clustering + primary-payer selection ---
    store.set_progress(phase="clustering", percent=70)
    clusters = cluster_wallets(contexts)
    paid_recent = store.get_paid_to_anchor_recent(anchor, settings.employer_window_days)
    primary = select_primary_payer(clusters, paid_recent)

    next_cluster_id = 1
    primary_members: set[str] = set()
    for cluster in clusters:
        is_primary = primary is not None and cluster.members == primary.members
        label = "primary_payer" if is_primary else "noise"
        store.insert_cluster(next_cluster_id, label, cluster.confidence)
        for m in cluster.members:
            store.upsert_wallet(
                m, role=("primary_payer" if is_primary else "noise"), cluster_id=next_cluster_id
            )
        if is_primary:
            primary_members = set(cluster.members)
        next_cluster_id += 1

    # --- Phase 6-7: counterparties + monthly aggregation ---
    store.set_progress(phase="aggregation", percent=85)
    primary_recipients: set[str] = set()
    for m in primary_members:
        primary_recipients |= store.get_recipients(m)

    counterparties, _needs_check = derive_counterparties(
        primary_recipients, anchor, exchange_addrs, payers=primary_members
    )
    for cp in counterparties:
        store.upsert_wallet(cp, role="counterparty")

    transfers = [
        Transfer(to, amt, ts)
        for (to, amt, ts) in store.outbound_transfers(primary_members)
        if to in counterparties
    ]
    store.write_monthly_stats(aggregate_monthly(transfers))

    store.set_progress(phase="done", percent=100)
