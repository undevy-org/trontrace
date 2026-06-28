"""Phase 1 — TronGrid client. No live calls: uses httpx.MockTransport (real httpx stack)."""
import asyncio

import httpx

from app.trongrid import (
    FetchResult,
    RateLimiter,
    TransferRecord,
    TronGridClient,
    normalize_transfer,
)


# --- normalization (pure) ---------------------------------------------------

def _raw(tx="h1", frm="TA", to="TB", value="1500000", ts_ms=1782632094000):
    return {
        "transaction_id": tx,
        "from": frm,
        "to": to,
        "value": value,
        "block_timestamp": ts_ms,
        "token_info": {"symbol": "USDT", "decimals": 6},
    }


def test_normalize_converts_ms_to_seconds_and_value_to_int():
    rec = normalize_transfer(_raw(value="2500000", ts_ms=1782632094000))
    assert isinstance(rec, TransferRecord)
    assert rec.amount_raw == 2_500_000        # string -> int, no float
    assert rec.timestamp == 1782632094         # ms -> s
    assert rec.token == "USDT"
    assert rec.from_address == "TA" and rec.to_address == "TB"


# --- pagination -------------------------------------------------------------

def _client(handler):
    return TronGridClient(transport=httpx.MockTransport(handler), rps=10_000)


def _collect(coro):
    return asyncio.run(coro)


def test_paginates_across_fingerprint_until_exhausted():
    pages = {
        None: {"data": [_raw("h1"), _raw("h2")], "meta": {"fingerprint": "fp1"}},
        "fp1": {"data": [_raw("h3")], "meta": {}},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        fp = request.url.params.get("fingerprint")
        return httpx.Response(200, json=pages[fp])

    async def run():
        async with _client(handler) as c:
            return await c.fetch_transfers("Tanchor", direction="in")

    result: FetchResult = _collect(run())
    assert [r.tx_hash for r in result.records] == ["h1", "h2", "h3"]
    assert result.cap_hit is False
    assert result.last_fingerprint is None


def test_cap_hit_stops_and_flags_when_more_pages_remain():
    pages = {
        None: {"data": [_raw("h1"), _raw("h2")], "meta": {"fingerprint": "fp1"}},
        "fp1": {"data": [_raw("h3")], "meta": {}},
    }

    def handler(request):
        fp = request.url.params.get("fingerprint")
        return httpx.Response(200, json=pages[fp])

    async def run():
        async with _client(handler) as c:
            return await c.fetch_transfers("Tanchor", direction="out", max_records=2)

    result = _collect(run())
    assert len(result.records) == 2          # trimmed to cap
    assert result.cap_hit is True            # more pages existed (fp1)


def test_skips_oversized_spoof_values():
    # Real USDT data contains spam transfers with value = 2**256-1. Such values exceed the
    # int64 storage ceiling and are provably fake (far above token supply) -> dropped.
    huge = str(2**256 - 1)
    pages = {None: {"data": [_raw("h1", value="1000000"), _raw("spam", value=huge)],
                    "meta": {}}}

    def handler(request):
        return httpx.Response(200, json=pages[request.url.params.get("fingerprint")])

    async def run():
        async with _client(handler) as c:
            return await c.fetch_transfers("Tanchor", direction="in")

    result = _collect(run())
    assert [r.tx_hash for r in result.records] == ["h1"]   # spam dropped
    assert result.skipped_oversized == 1


def test_retries_on_429_then_succeeds():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, json={})
        return httpx.Response(200, json={"data": [_raw("h1")], "meta": {}})

    async def run():
        async with TronGridClient(
            transport=httpx.MockTransport(handler), rps=10_000, backoff_base=0.0
        ) as c:
            return await c.fetch_transfers("Tanchor", direction="in")

    result = _collect(run())
    assert calls["n"] == 2
    assert [r.tx_hash for r in result.records] == ["h1"]


# --- rate limiter (deterministic via injected clock) ------------------------

def test_rate_limiter_sleeps_for_remaining_interval():
    slept = []
    times = iter([0.0, 0.03])  # two wait() calls; min interval at rps=10 is 0.1s

    async def fake_sleep(d):
        slept.append(d)

    async def run():
        rl = RateLimiter(rps=10, now=lambda: next(times), sleep=fake_sleep)
        await rl.wait()   # first call: no previous timestamp -> no sleep
        await rl.wait()   # elapsed 0.03 < 0.1 -> sleep remaining 0.07

    _collect(run())
    assert len(slept) == 1
    assert abs(slept[0] - 0.07) < 1e-9
