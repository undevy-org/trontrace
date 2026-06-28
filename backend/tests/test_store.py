from app import store
from app.trongrid import TransferRecord


def _tx(h, frm, to, amt, ts):
    return TransferRecord(h, frm, to, amt, ts, "USDT")


def test_insert_and_dedupe_transactions(temp_db):
    txs = [_tx("h1", "A", "B", 100, 1000), _tx("h1", "A", "B", 100, 1000)]
    store.insert_transactions(txs)          # second is a duplicate tx_hash
    store.insert_transactions([_tx("h2", "A", "C", 50, 1100)])
    assert store.count_transactions() == 2


def test_candidates_are_distinct_senders_to_anchor(temp_db):
    store.insert_transactions([
        _tx("h1", "P1", "ANCHOR", 100, 1000),
        _tx("h2", "P1", "ANCHOR", 100, 1100),   # same sender again
        _tx("h3", "P2", "ANCHOR", 100, 1200),
        _tx("h4", "P1", "OTHER", 100, 1300),     # not to anchor -> ignored
    ])
    assert store.get_candidates("ANCHOR") == {"P1", "P2"}


def test_wallet_context_queries(temp_db):
    store.insert_transactions([
        _tx("o1", "P1", "X", 10, 2000),
        _tx("o2", "P1", "Y", 20, 2100),
        _tx("f1", "SRC", "P1", 99, 1000),   # funding of P1
    ])
    assert store.get_recipients("P1") == {"X", "Y"}
    assert store.get_funding_sources("P1") == {"SRC"}
    ts, amts = store.get_outbound_series("P1")
    assert ts == [2000, 2100]
    assert amts == [10, 20]


def test_inbound_rows_returns_from_amount_timestamp(temp_db):
    store.insert_transactions([
        _tx("i1", "SRC1", "R1", 100, 3000),
        _tx("i2", "SRC2", "R1", 200, 3100),
        _tx("o1", "R1", "OUT", 50, 3200),   # outbound from R1 -> ignored
    ])
    rows = store.get_inbound_rows("R1")
    assert sorted(rows) == [("SRC1", 100, 3000), ("SRC2", 200, 3100)]
    assert store.get_inbound_rows("UNKNOWN") == []


def test_paid_to_anchor_within_window(temp_db):
    # last inbound at ts=10_000_000; window of 1 day = 86400s -> cutoff 9_913_600
    store.insert_transactions([
        _tx("h1", "P1", "ANCHOR", 500, 10_000_000),   # in window
        _tx("h2", "P1", "ANCHOR", 100, 9_000_000),     # out of window
        _tx("h3", "P2", "ANCHOR", 300, 9_999_000),     # in window
    ])
    paid = store.get_paid_to_anchor_recent("ANCHOR", window_days=1)
    assert paid == {"P1": 500, "P2": 300}


def test_progress_roundtrip(temp_db):
    store.set_progress(anchor="ANCHOR", phase="inbound", percent=20)
    p = store.get_progress()
    assert p["phase"] == "inbound" and p["percent"] == 20


def test_entity_nodes_roundtrip_ordered_by_confidence(temp_db):
    store.upsert_entity_node("R1", kind="recipient", confidence=0.9, tier="high",
                             months_active=12, total_raw=72_000000, n_payers=2)
    store.upsert_entity_node("R2", kind="recipient", confidence=0.5, tier="med",
                             months_active=4, total_raw=20_000000, n_payers=1)
    store.upsert_entity_node("W3", kind="payer", confidence=0.8, tier="high")
    recips = store.read_entity_nodes("recipient")
    assert [r["address"] for r in recips] == ["R1", "R2"]   # confidence desc
    assert store.read_entity_nodes("payer")[0]["address"] == "W3"


def test_cohort_timelines_groups_by_address(temp_db):
    from app.analysis.monthly import MonthlyCell
    store.write_monthly_stats([
        MonthlyCell("R1", "2025-01", 3_000000, 1),
        MonthlyCell("R1", "2025-02", 3_000000, 1),
        MonthlyCell("R2", "2025-01", 5_000000, 1),
    ])
    tl = store.cohort_timelines()
    assert tl["R1"] == [("2025-01", 3_000000), ("2025-02", 3_000000)]
    assert tl["R2"] == [("2025-01", 5_000000)]
