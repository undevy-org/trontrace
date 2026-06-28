"""Persistence layer: all SQLite reads/writes live here.

Keeps SQL out of the pipeline and the API. Amounts are integer base units throughout.
"""
from __future__ import annotations

import time
from collections.abc import Iterable

from .db import connect
from .trongrid import TransferRecord

# --- transactions -----------------------------------------------------------


def insert_transactions(txs: Iterable[TransferRecord]) -> None:
    rows = [
        (t.tx_hash, t.from_address, t.to_address, t.amount_raw, t.timestamp, t.token)
        for t in txs
    ]
    if not rows:
        return
    with connect() as conn:
        conn.executemany(
            "INSERT OR IGNORE INTO transactions "
            "(tx_hash, from_address, to_address, amount_raw, timestamp, token) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            rows,
        )


def count_transactions() -> int:
    with connect() as conn:
        return conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]


# --- graph queries ----------------------------------------------------------


def get_candidates(anchor: str) -> set[str]:
    """Distinct addresses that sent the token to the anchor."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT DISTINCT from_address FROM transactions WHERE to_address = ?",
            (anchor,),
        ).fetchall()
    return {r[0] for r in rows}


def get_recipients(address: str) -> set[str]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT DISTINCT to_address FROM transactions WHERE from_address = ?",
            (address,),
        ).fetchall()
    return {r[0] for r in rows}


def get_funding_sources(address: str) -> set[str]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT DISTINCT from_address FROM transactions WHERE to_address = ?",
            (address,),
        ).fetchall()
    return {r[0] for r in rows}


def get_outbound_series(address: str) -> tuple[list[int], list[int]]:
    """(timestamps, amounts) of this address's outbound transfers, ordered by time."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT timestamp, amount_raw FROM transactions "
            "WHERE from_address = ? ORDER BY timestamp",
            (address,),
        ).fetchall()
    return [r[0] for r in rows], [r[1] for r in rows]


def get_paid_to_anchor_recent(anchor: str, window_days: int) -> dict[str, int]:
    """Per-sender total paid to the anchor within `window_days` of the last inbound tx."""
    with connect() as conn:
        last = conn.execute(
            "SELECT MAX(timestamp) FROM transactions WHERE to_address = ?", (anchor,)
        ).fetchone()[0]
        if last is None:
            return {}
        cutoff = last - window_days * 86400
        rows = conn.execute(
            "SELECT from_address, SUM(amount_raw) FROM transactions "
            "WHERE to_address = ? AND timestamp >= ? GROUP BY from_address",
            (anchor, cutoff),
        ).fetchall()
    return {r[0]: r[1] for r in rows}


def outbound_transfers(addresses: set[str]) -> list[tuple[str, int, int]]:
    """(to_address, amount_raw, timestamp) for transfers FROM any of `addresses`."""
    if not addresses:
        return []
    placeholders = ",".join("?" * len(addresses))
    with connect() as conn:
        rows = conn.execute(
            f"SELECT to_address, amount_raw, timestamp FROM transactions "
            f"WHERE from_address IN ({placeholders})",
            tuple(addresses),
        ).fetchall()
    return [(r[0], r[1], r[2]) for r in rows]


def get_inbound_rows(address: str) -> list[tuple[str, int, int]]:
    """(from_address, amount_raw, timestamp) for transfers TO `address`."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT from_address, amount_raw, timestamp FROM transactions "
            "WHERE to_address = ?",
            (address,),
        ).fetchall()
    return [(r[0], r[1], r[2]) for r in rows]


# --- wallets / roles / clusters ---------------------------------------------


def upsert_wallet(
    address: str,
    *,
    role: str | None = None,
    cluster_id: int | None = None,
    first_seen: int | None = None,
    last_seen: int | None = None,
) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO wallets (address, role, cluster_id, first_seen, last_seen) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(address) DO UPDATE SET "
            "  role = COALESCE(excluded.role, wallets.role), "
            "  cluster_id = COALESCE(excluded.cluster_id, wallets.cluster_id), "
            "  first_seen = COALESCE(excluded.first_seen, wallets.first_seen), "
            "  last_seen = COALESCE(excluded.last_seen, wallets.last_seen)",
            (address, role, cluster_id, first_seen, last_seen),
        )


def set_role(address: str, role: str) -> None:
    upsert_wallet(address, role=role)


def get_wallets_by_role(role: str) -> list[str]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT address FROM wallets WHERE role = ? ORDER BY address", (role,)
        ).fetchall()
    return [r[0] for r in rows]


def get_wallet(address: str) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM wallets WHERE address = ?", (address,)).fetchone()
    return dict(row) if row else None


def insert_cluster(cluster_id: int, label: str, confidence: float) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO clusters (cluster_id, label, confidence, created_at) "
            "VALUES (?, ?, ?, ?)",
            (cluster_id, label, confidence, int(time.time())),
        )


def get_cluster(cluster_id: int) -> dict | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM clusters WHERE cluster_id = ?", (cluster_id,)
        ).fetchone()
    return dict(row) if row else None


# --- monthly stats ----------------------------------------------------------


def write_monthly_stats(cells: Iterable) -> None:
    rows = [
        (c.counterparty_address, c.year_month, c.total_raw, c.tx_count) for c in cells
    ]
    with connect() as conn:
        conn.execute("DELETE FROM monthly_stats")
        if rows:
            conn.executemany(
                "INSERT OR REPLACE INTO monthly_stats "
                "(counterparty_address, year_month, total_raw, tx_count) VALUES (?, ?, ?, ?)",
                rows,
            )


def read_monthly_stats(date_from: str | None = None, date_to: str | None = None) -> list[dict]:
    q = "SELECT counterparty_address, year_month, total_raw, tx_count FROM monthly_stats"
    clauses, params = [], []
    if date_from:
        clauses.append("year_month >= ?")
        params.append(date_from)
    if date_to:
        clauses.append("year_month <= ?")
        params.append(date_to)
    if clauses:
        q += " WHERE " + " AND ".join(clauses)
    q += " ORDER BY counterparty_address, year_month"
    with connect() as conn:
        rows = conn.execute(q, tuple(params)).fetchall()
    return [dict(r) for r in rows]


# --- progress / checkpoint --------------------------------------------------


def set_progress(
    *,
    anchor: str | None = None,
    phase: str | None = None,
    percent: int | None = None,
    last_candidate: str | None = None,
    last_fingerprint: str | None = None,
) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO progress "
            "(id, anchor, phase, last_candidate, last_fingerprint, percent, updated_at) "
            "VALUES (1, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET "
            "  anchor = COALESCE(excluded.anchor, progress.anchor), "
            "  phase = COALESCE(excluded.phase, progress.phase), "
            "  last_candidate = COALESCE(excluded.last_candidate, progress.last_candidate), "
            "  last_fingerprint = excluded.last_fingerprint, "
            "  percent = COALESCE(excluded.percent, progress.percent), "
            "  updated_at = excluded.updated_at",
            (anchor, phase, last_candidate, last_fingerprint, percent, int(time.time())),
        )


def get_progress() -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM progress WHERE id = 1").fetchone()
    return dict(row) if row else None


# --- API read helpers (raw amounts; formatting happens in the API layer) -----


def get_anchor() -> str | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT address FROM wallets WHERE role = 'anchor' LIMIT 1"
        ).fetchone()
    return row[0] if row else None


def cluster_confidence_for(address: str) -> float | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT c.confidence FROM wallets w JOIN clusters c ON w.cluster_id = c.cluster_id "
            "WHERE w.address = ?",
            (address,),
        ).fetchone()
    return row[0] if row else None


def anchor_monthly_raw(anchor: str) -> dict[str, int]:
    """Per-UTC-month total the anchor received (the 'You' row)."""
    from .analysis.monthly import year_month_utc

    with connect() as conn:
        rows = conn.execute(
            "SELECT timestamp, amount_raw FROM transactions WHERE to_address = ?",
            (anchor,),
        ).fetchall()
    out: dict[str, int] = {}
    for ts, amt in rows:
        ym = year_month_utc(ts)
        out[ym] = out.get(ym, 0) + amt
    return out


def overview_raw(anchor: str) -> dict:
    primary = [
        {"address": a, "confidence": cluster_confidence_for(a) or 0.0}
        for a in get_wallets_by_role("primary_payer")
    ]
    monthly = anchor_monthly_raw(anchor)
    total = sum(monthly.values())
    avg = total // len(monthly) if monthly else 0
    counterparties = {s["counterparty_address"] for s in read_monthly_stats()}
    return {
        "anchor": anchor,
        "primary_payer": {
            "wallets": primary,
            "confidence": max((p["confidence"] for p in primary), default=0.0),
        },
        "totals": {"received_raw": total, "monthly_avg_raw": avg},
        "counterparty_count": len(counterparties),
        "exchanges": get_wallets_by_role("exchange"),
        "noise": get_wallets_by_role("noise"),
    }


def wallet_detail_raw(address: str) -> dict | None:
    w = get_wallet(address)
    with connect() as conn:
        bounds = conn.execute(
            "SELECT MIN(timestamp), MAX(timestamp) FROM transactions "
            "WHERE from_address = ? OR to_address = ?",
            (address, address),
        ).fetchone()
        top_recipients = conn.execute(
            "SELECT to_address, SUM(amount_raw) s FROM transactions WHERE from_address = ? "
            "GROUP BY to_address ORDER BY s DESC LIMIT 5",
            (address,),
        ).fetchall()
        top_senders = conn.execute(
            "SELECT from_address, SUM(amount_raw) s FROM transactions WHERE to_address = ? "
            "GROUP BY from_address ORDER BY s DESC LIMIT 5",
            (address,),
        ).fetchall()
    if w is None and bounds[0] is None:
        return None
    return {
        "address": address,
        "role": (w or {}).get("role"),
        "confidence": cluster_confidence_for(address),
        "first_seen": bounds[0],
        "last_seen": bounds[1],
        "top_recipients": [{"address": r[0], "total_raw": r[1]} for r in top_recipients],
        "top_senders": [{"address": r[0], "total_raw": r[1]} for r in top_senders],
    }


def graph_raw(month: str | None = None) -> dict:
    """Nodes = role-bearing wallets; edges = aggregated transfers between them."""
    from .analysis.monthly import year_month_utc

    with connect() as conn:
        wrows = conn.execute(
            "SELECT address, role FROM wallets WHERE role IS NOT NULL"
        ).fetchall()
        roles = {r[0]: r[1] for r in wrows}
        trows = conn.execute(
            "SELECT from_address, to_address, amount_raw, timestamp FROM transactions"
        ).fetchall()

    weights: dict[tuple[str, str], int] = {}
    for frm, to, amt, ts in trows:
        if frm not in roles or to not in roles:
            continue
        if month and year_month_utc(ts) != month:
            continue
        weights[(frm, to)] = weights.get((frm, to), 0) + amt

    return {
        "nodes": [{"id": a, "role": r} for a, r in roles.items()],
        "edges": [
            {"source": s, "target": t, "weight_raw": w} for (s, t), w in weights.items()
        ],
    }


# --- entity nodes -----------------------------------------------------------


def upsert_entity_node(address, *, kind, confidence, tier, first_pay=None, last_pay=None,
                       months_active=None, total_raw=None, n_payers=None, discovered_round=None):
    with connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO entity_nodes "
            "(address, kind, confidence, tier, first_pay, last_pay, months_active, "
            " total_raw, n_payers, discovered_round) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (address, kind, confidence, tier, first_pay, last_pay, months_active,
             total_raw, n_payers, discovered_round),
        )


def read_entity_nodes(kind: str) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM entity_nodes WHERE kind = ? ORDER BY confidence DESC, address",
            (kind,),
        ).fetchall()
    return [dict(r) for r in rows]


# --- cohort timelines -------------------------------------------------------


def cohort_timelines() -> dict[str, list[tuple[str, int]]]:
    """address -> sorted [(year_month, total_raw)] from monthly_stats."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT counterparty_address, year_month, total_raw FROM monthly_stats "
            "ORDER BY counterparty_address, year_month"
        ).fetchall()
    out: dict[str, list[tuple[str, int]]] = {}
    for addr, ym, raw in rows:
        out.setdefault(addr, []).append((ym, raw))
    return out
