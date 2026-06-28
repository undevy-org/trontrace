import asyncio

import httpx
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.pipeline import run_analysis
from app.trongrid import TronGridClient
from scheme_fixture import handler


def _seed():
    async def run():
        async with TronGridClient(transport=httpx.MockTransport(handler), rps=10_000) as c:
            await run_analysis("ANCHOR", c)
    asyncio.run(run())


def test_analyze_rejects_invalid_address(temp_db):
    client = TestClient(app)
    r = client.post("/api/analyze", json={"address": "not-an-address"})
    assert r.status_code == 400


def test_status_and_overview_after_seed(temp_db):
    old = settings.fanout_cap
    settings.fanout_cap = 2
    try:
        _seed()
        client = TestClient(app)

        s = client.get("/api/status")
        assert s.status_code == 200 and s.json()["phase"] == "done"

        o = client.get("/api/overview").json()
        assert {w["address"] for w in o["primary_payer"]["wallets"]} == {"E1", "E2"}
        assert o["counterparty_count"] == 2
        assert o["exchanges"] == ["EXf"]
    finally:
        settings.fanout_cap = old


def test_monthly_and_csv(temp_db):
    old = settings.fanout_cap
    settings.fanout_cap = 2
    try:
        _seed()
        client = TestClient(app)

        m = client.get("/api/monthly").json()
        addrs = {row["address"] for row in m["rows"]}
        assert "C1" in addrs and "You" in addrs    # counterparties + anchor row

        csv = client.get("/api/export/csv")
        assert csv.status_code == 200
        assert "counterparty" in csv.text.splitlines()[0].lower()
        assert "C1" in csv.text
    finally:
        settings.fanout_cap = old


def test_wallet_and_graph(temp_db):
    old = settings.fanout_cap
    settings.fanout_cap = 2
    try:
        _seed()
        client = TestClient(app)

        w = client.get("/api/wallet/E1").json()
        assert w["role"] == "primary_payer"

        g = client.get("/api/graph").json()
        node_ids = {n["id"] for n in g["nodes"]}
        assert {"ANCHOR", "E1", "E2", "C1"} <= node_ids
        assert all("weight_raw" not in e for e in g["edges"])  # API formats to decimal string
    finally:
        settings.fanout_cap = old


def test_cohort_and_entity_wallets_endpoints(temp_db):
    from app import store
    store.upsert_entity_node("R1", kind="recipient", confidence=0.9, tier="high",
                             months_active=12, total_raw=72_000000, n_payers=2)
    store.upsert_entity_node("W3", kind="payer", confidence=0.8, tier="high")
    client = TestClient(app)
    cohort = client.get("/api/cohort").json()
    assert cohort["recipients"][0]["address"] == "R1"
    assert cohort["recipients"][0]["total"] == "72"      # decimal-formatted
    wallets = client.get("/api/entity-wallets").json()
    assert wallets["wallets"][0]["address"] == "W3"
