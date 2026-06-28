"""SQLite schema + connection.

Amounts are stored as INTEGER base units (raw token decimals) — never floats — so monthly
sums are exact. Conversion to a decimal string happens only at the display/CSV boundary.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from .config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS wallets (
    address      TEXT PRIMARY KEY,
    first_seen   INTEGER,            -- unix seconds, UTC
    last_seen    INTEGER,
    role         TEXT,               -- 'anchor'|'primary_payer'|'counterparty'|'noise'|'exchange'
    cluster_id   INTEGER
);

CREATE TABLE IF NOT EXISTS transactions (
    tx_hash      TEXT PRIMARY KEY,
    from_address TEXT NOT NULL,
    to_address   TEXT NOT NULL,
    amount_raw   INTEGER NOT NULL,   -- base units (token_decimals)
    timestamp    INTEGER NOT NULL,   -- unix seconds, UTC
    token        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS clusters (
    cluster_id   INTEGER PRIMARY KEY,
    label        TEXT,
    confidence   REAL,               -- [0,1]
    created_at   INTEGER
);

CREATE TABLE IF NOT EXISTS monthly_stats (
    counterparty_address TEXT NOT NULL,
    year_month           TEXT NOT NULL,   -- 'YYYY-MM' (UTC)
    total_raw            INTEGER NOT NULL,
    tx_count             INTEGER NOT NULL,
    PRIMARY KEY (counterparty_address, year_month)
);

CREATE TABLE IF NOT EXISTS progress (
    id               INTEGER PRIMARY KEY CHECK (id = 1),
    anchor           TEXT,
    phase            TEXT,
    last_candidate   TEXT,
    last_fingerprint TEXT,
    percent          INTEGER,
    updated_at       INTEGER
);

CREATE TABLE IF NOT EXISTS entity_nodes (
    address          TEXT PRIMARY KEY,
    kind             TEXT NOT NULL,     -- 'payer' | 'recipient'
    confidence       REAL,
    tier             TEXT,              -- 'high' | 'med' | 'low'
    first_pay        INTEGER,
    last_pay         INTEGER,
    months_active    INTEGER,
    total_raw        INTEGER,
    n_payers         INTEGER,
    discovered_round INTEGER
);

CREATE INDEX IF NOT EXISTS idx_tx_from    ON transactions(from_address);
CREATE INDEX IF NOT EXISTS idx_tx_to      ON transactions(to_address);
CREATE INDEX IF NOT EXISTS idx_tx_time    ON transactions(timestamp);
CREATE INDEX IF NOT EXISTS idx_wallet_cluster ON wallets(cluster_id);
"""


def connect() -> sqlite3.Connection:
    Path(settings.db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)
