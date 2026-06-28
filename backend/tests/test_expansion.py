"""Bipartite expansion: discover an unknown payer wallet + cohort, exclude decoys."""
import asyncio
from datetime import datetime, timezone

import httpx

from app import store
from app.expansion import run_expansion
from app.trongrid import TronGridClient

USDT = {"symbol": "USDT", "decimals": 6}


def _ts(m, d):
    return int(datetime(2025, m, d, tzinfo=timezone.utc).timestamp())


def _r(tx, frm, to, val, ts):
    return {"transaction_id": tx, "from": frm, "to": to, "value": str(val),
            "block_timestamp": ts * 1000, "token_info": USDT}


# W1,W2 pay the anchor (seed). W3 is UNKNOWN (never pays anchor) but co-pays R1,R2,R3 on
# pay-cycle day 1. EXHUB = exchange (200 senders). UNREL pays only R1 (< K) -> rejected.
def _outbound(addr):
    out = {
        "W1": [_r("w1a", "W1", "ANCHOR", 6_000000, _ts(m, 1)) for m in range(1, 7)]
              + [_r(f"w1r1{m}", "W1", "R1", 5_000000, _ts(m, 1)) for m in range(1, 7)]
              + [_r(f"w1r2{m}", "W1", "R2", 4_000000, _ts(m, 1)) for m in range(1, 7)]
              + [_r("w1ex", "W1", "EXHUB", 9_000000, _ts(2, 9))],
        "W2": [_r(f"w2r1{m}", "W2", "R1", 5_000000, _ts(m, 1)) for m in range(1, 7)]
              + [_r(f"w2r3{m}", "W2", "R3", 3_000000, _ts(m, 1)) for m in range(1, 7)],
        "W3": [_r(f"w3r1{m}", "W3", "R1", 5_000000, _ts(m, 1)) for m in range(1, 7)]
              + [_r(f"w3r2{m}", "W3", "R2", 4_000000, _ts(m, 1)) for m in range(1, 7)]
              + [_r(f"w3r3{m}", "W3", "R3", 3_000000, _ts(m, 1)) for m in range(1, 7)],
        "UNREL": [_r("ur1", "UNREL", "R1", 1_000000, _ts(3, 9))],
    }
    return out.get(addr, [])


def _inbound(addr):
    inb = {
        "R1": ([_r(f"w1r1{m}", "W1", "R1", 5_000000, _ts(m, 1)) for m in range(1, 7)]
               + [_r(f"w2r1{m}", "W2", "R1", 5_000000, _ts(m, 1)) for m in range(1, 7)]
               + [_r(f"w3r1{m}", "W3", "R1", 5_000000, _ts(m, 1)) for m in range(1, 7)]
               + [_r("ur1", "UNREL", "R1", 1_000000, _ts(3, 9))]),
        "R2": ([_r(f"w1r2{m}", "W1", "R2", 4_000000, _ts(m, 1)) for m in range(1, 7)]
               + [_r(f"w3r2{m}", "W3", "R2", 4_000000, _ts(m, 1)) for m in range(1, 7)]),
        "R3": ([_r(f"w2r3{m}", "W2", "R3", 3_000000, _ts(m, 1)) for m in range(1, 7)]
               + [_r(f"w3r3{m}", "W3", "R3", 3_000000, _ts(m, 1)) for m in range(1, 7)]),
        "EXHUB": [_r(f"ex{i}", f"S{i}", "EXHUB", 1_000000, _ts(2, 9)) for i in range(200)],
    }
    return inb.get(addr, [])


def _handler(request):
    addr = request.url.path.split("/")[3]
    direction = "in" if request.url.params.get("only_to") else "out"
    data = _inbound(addr) if direction == "in" else _outbound(addr)
    return httpx.Response(200, json={"data": data, "meta": {}})


def test_expansion_discovers_unknown_payer_and_cohort(temp_db):
    async def run():
        async with TronGridClient(transport=httpx.MockTransport(_handler), rps=10_000) as c:
            await run_expansion("ANCHOR", c, seed_payers={"W1", "W2"})

    asyncio.run(run())

    payers = {n["address"] for n in store.read_entity_nodes("payer")}
    cohort = {n["address"] for n in store.read_entity_nodes("recipient")}
    assert "W3" in payers                 # unknown wallet discovered
    assert {"R1", "R2", "R3"} <= cohort   # full cohort found
    assert "EXHUB" not in cohort          # exchange excluded
    assert "UNREL" not in payers          # below corroboration K


# Regression: a known payer (W2) that receives a payer-to-payer transit from another payer (W1)
# must NOT be scored as a recipient — that would overwrite its payer node (INSERT OR REPLACE).
def _transit_outbound(addr):
    out = {
        "W1": [_r("w1a", "W1", "ANCHOR", 6_000000, _ts(m, 1)) for m in range(1, 7)]
              + [_r(f"w1r1{m}", "W1", "R1", 5_000000, _ts(m, 1)) for m in range(1, 7)]
              + [_r("w1w2", "W1", "W2", 7_000000, _ts(2, 3))],   # payer-to-payer transit
        "W2": [_r("w2a", "W2", "ANCHOR", 6_000000, _ts(m, 1)) for m in range(1, 7)]
              + [_r(f"w2r1{m}", "W2", "R1", 5_000000, _ts(m, 1)) for m in range(1, 7)],
    }
    return out.get(addr, [])


def _transit_inbound(addr):
    inb = {
        "R1": ([_r(f"w1r1{m}", "W1", "R1", 5_000000, _ts(m, 1)) for m in range(1, 7)]
               + [_r(f"w2r1{m}", "W2", "R1", 5_000000, _ts(m, 1)) for m in range(1, 7)]),
        "W2": [_r("w1w2", "W1", "W2", 7_000000, _ts(2, 3))],
    }
    return inb.get(addr, [])


def _transit_handler(request):
    addr = request.url.path.split("/")[3]
    direction = "in" if request.url.params.get("only_to") else "out"
    data = _transit_inbound(addr) if direction == "in" else _transit_outbound(addr)
    return httpx.Response(200, json={"data": data, "meta": {}})


def test_known_payer_not_reclassified_as_recipient(temp_db):
    async def run():
        async with TronGridClient(transport=httpx.MockTransport(_transit_handler), rps=10_000) as c:
            await run_expansion("ANCHOR", c, seed_payers={"W1", "W2"})

    asyncio.run(run())

    recipients = {n["address"] for n in store.read_entity_nodes("recipient")}
    assert "W2" not in recipients   # payer-to-payer transit must not reclassify a payer
    assert "R1" in recipients       # genuine recipient still found
