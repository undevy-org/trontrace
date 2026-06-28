"""Background analysis manager.

Runs one analysis at a time as an in-process asyncio task. Progress and the last-fetched
cursor are checkpointed in the `progress` table by the pipeline, so an interrupted run can be
re-started safely: all inserts are idempotent (INSERT OR IGNORE), so re-running never loses or
duplicates data. (True fingerprint-level skip-resume is a later refinement; correctness holds.)
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable

from . import store
from .pipeline import run_analysis
from .trongrid import TronGridClient


class AnalysisAlreadyRunning(Exception):
    """Raised when an analysis is requested while another is in progress."""


class AnalysisManager:
    def __init__(self, client_factory: Callable[[], TronGridClient] | None = None) -> None:
        self._factory = client_factory or (lambda: TronGridClient())
        self._task: asyncio.Task | None = None

    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def _run(self, anchor: str) -> None:
        async with self._factory() as client:
            await run_analysis(anchor, client)

    def start_task(self, anchor: str) -> asyncio.Task:
        """Schedule the analysis and return the task. Raises if one is already running."""
        if self.is_running():
            raise AnalysisAlreadyRunning()
        self._task = asyncio.create_task(self._run(anchor))
        return self._task

    async def start(self, anchor: str) -> None:
        """Run an analysis to completion (convenience wrapper around start_task)."""
        await self.start_task(anchor)

    def status(self) -> dict:
        return store.get_progress() or {"phase": "idle", "percent": 0}


# Process-wide singleton used by the API.
manager = AnalysisManager()
