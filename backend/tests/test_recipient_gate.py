"""v1.1 recipient-side fan-in gate: a counterparty fed by many senders is flagged exchange."""
import asyncio

import httpx

from app import store
from app.config import settings
from app.pipeline import run_analysis
from app.trongrid import TronGridClient

USDT = {"symbol": "USDT", "decimals": 6}
T = 1768435200


def _r(tx, frm, to, val):
    return {"transaction_id": tx, "from": frm, "to": to, "value": str(val),
            "block_timestamp": T * 1000, "token_info": USDT}


# E1 pays the anchor, and pays C1 (private) + HUB (fed by 60 distinct senders -> exchange).
SCHEME = {
    ("ANCHOR", "in"): [_r("i1", "E1", "ANCHOR", 100_000000)],
    ("E1", "out"): [_r("i1", "E1", "ANCHOR", 100_000000),
                    _r("e1c1", "E1", "C1", 30_000000),
                    _r("e1hub", "E1", "HUB", 50_000000)],
    ("E1", "in"): [_r("f1", "F", "E1", 100_000000)],
    ("C1", "in"): [_r("e1c1", "E1", "C1", 30_000000)],            # 1 sender -> private
    ("HUB", "in"): [_r(f"h{i}", f"S{i}", "HUB", 1_000000) for i in range(60)],  # 60 senders
}


def _handler(request):
    address = request.url.path.split("/")[3]
    direction = "in" if request.url.params.get("only_to") else "out"
    return httpx.Response(200, json={"data": SCHEME.get((address, direction), []), "meta": {}})


def test_recipient_gate_drops_high_fanin_counterparty(temp_db):
    old_gate = settings.recipient_gate
    settings.recipient_gate = True
    try:
        async def run():
            async with TronGridClient(transport=httpx.MockTransport(_handler), rps=10_000) as c:
                await run_analysis("ANCHOR", c)
        asyncio.run(run())

        # HUB flagged as exchange and dropped; C1 stays a counterparty.
        assert store.get_wallet("HUB")["role"] == "exchange"
        cps = {s["counterparty_address"] for s in store.read_monthly_stats()}
        assert cps == {"C1"}
    finally:
        settings.recipient_gate = old_gate
