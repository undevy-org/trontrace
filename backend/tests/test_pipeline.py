"""Phase 2-6 integration: full pipeline over a synthetic scheme via MockTransport."""
import asyncio

import httpx

from app import store
from app.analysis.monthly import year_month_utc
from app.config import settings
from app.pipeline import run_analysis
from app.trongrid import TronGridClient
from scheme_fixture import FEB, JAN, handler


def test_full_pipeline_clusters_and_aggregates(temp_db):
    old_fanout = settings.fanout_cap
    settings.fanout_cap = 2          # EXf has 3 recipients -> flagged; E1/E2 have 2 -> kept
    try:
        async def run():
            async with TronGridClient(transport=httpx.MockTransport(handler), rps=10_000) as c:
                await run_analysis("ANCHOR", c)

        asyncio.run(run())

        assert set(store.get_wallets_by_role("primary_payer")) == {"E1", "E2"}
        assert store.get_wallets_by_role("noise") == ["N1"]
        assert store.get_wallets_by_role("exchange") == ["EXf"]

        stats = store.read_monthly_stats()
        assert {s["counterparty_address"] for s in stats} == {"C1", "C2"}

        c1 = {s["year_month"]: s["total_raw"] for s in stats if s["counterparty_address"] == "C1"}
        assert c1 == {year_month_utc(JAN): 30_000000, year_month_utc(FEB): 31_000000}

        assert store.get_progress()["phase"] == "done"
    finally:
        settings.fanout_cap = old_fanout
