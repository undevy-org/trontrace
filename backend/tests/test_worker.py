import asyncio

import httpx
import pytest

from app.config import settings
from app.trongrid import TronGridClient
from app.worker import AnalysisAlreadyRunning, AnalysisManager
from scheme_fixture import handler


def _factory():
    return TronGridClient(transport=httpx.MockTransport(handler), rps=10_000)


def test_worker_runs_to_completion(temp_db):
    old = settings.fanout_cap
    settings.fanout_cap = 2
    try:
        mgr = AnalysisManager(client_factory=_factory)

        async def run():
            await mgr.start("ANCHOR")

        asyncio.run(run())
        assert mgr.status()["phase"] == "done"
    finally:
        settings.fanout_cap = old


def test_worker_rejects_concurrent_runs(temp_db):
    settings.fanout_cap = 2
    mgr = AnalysisManager(client_factory=_factory)

    async def run():
        task = mgr.start_task("ANCHOR")
        with pytest.raises(AnalysisAlreadyRunning):
            mgr.start_task("ANCHOR")
        await task

    asyncio.run(run())


def test_status_idle_before_any_run(temp_db):
    mgr = AnalysisManager(client_factory=_factory)
    assert mgr.status()["phase"] == "idle"
