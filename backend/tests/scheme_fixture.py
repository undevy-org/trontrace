"""Shared synthetic TRON scheme for pipeline/worker tests (importable by sibling test modules)."""
import httpx

USDT = {"symbol": "USDT", "decimals": 6}
JAN = 1768435200   # 2026-01-15 UTC
FEB = 1771113600   # 2026-02-15 UTC


def _r(tx, frm, to, val, ts):
    return {"transaction_id": tx, "from": frm, "to": to, "value": str(val),
            "block_timestamp": ts * 1000, "token_info": USDT}


SCHEME = {
    ("ANCHOR", "in"): [
        _r("i1", "E1", "ANCHOR", 100_000000, JAN),
        _r("i2", "E2", "ANCHOR", 100_000000, FEB),
        _r("i3", "N1", "ANCHOR", 50_000000, JAN),
        _r("i4", "EXf", "ANCHOR", 10_000000, JAN),
    ],
    ("E1", "out"): [
        _r("i1", "E1", "ANCHOR", 100_000000, JAN),
        _r("e1c1", "E1", "C1", 30_000000, JAN),
        _r("e1c2", "E1", "C2", 20_000000, JAN),
    ],
    ("E2", "out"): [
        _r("i2", "E2", "ANCHOR", 100_000000, FEB),
        _r("e2c1", "E2", "C1", 31_000000, FEB),
        _r("e2c2", "E2", "C2", 21_000000, FEB),
    ],
    ("N1", "out"): [
        _r("i3", "N1", "ANCHOR", 50_000000, JAN),
        _r("n1z9", "N1", "Z9", 5_000000, JAN),
    ],
    ("EXf", "out"): [
        _r("x0", "EXf", "ANCHOR", 10_000000, JAN),
        _r("x1", "EXf", "Z1", 1, JAN),
        _r("x2", "EXf", "Z2", 1, JAN),
        _r("x3", "EXf", "Z3", 1, JAN),
    ],
    ("E1", "in"): [_r("f1", "F", "E1", 100_000000, JAN)],
    ("E2", "in"): [_r("f2", "F", "E2", 100_000000, FEB)],
    ("N1", "in"): [_r("g1", "G", "N1", 50_000000, JAN)],
}


def handler(request: httpx.Request) -> httpx.Response:
    address = request.url.path.split("/")[3]
    direction = "in" if request.url.params.get("only_to") else "out"
    return httpx.Response(200, json={"data": SCHEME.get((address, direction), []), "meta": {}})
