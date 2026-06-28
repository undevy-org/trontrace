"""REST routes. Raw integer amounts from the store are formatted to decimal strings here."""
from __future__ import annotations

import csv
import io
import re

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from . import store
from .analysis.monthly import raw_to_decimal_str
from .config import settings
from .worker import AnalysisAlreadyRunning, manager

router = APIRouter(prefix="/api")

_TRON_ADDRESS = re.compile(r"^T[1-9A-HJ-NP-Za-km-z]{33}$")


def _fmt(raw: int | None) -> str:
    return raw_to_decimal_str(raw or 0, settings.token_decimals)


class AnalyzeRequest(BaseModel):
    address: str


@router.post("/analyze")
async def analyze(req: AnalyzeRequest):
    if not _TRON_ADDRESS.match(req.address):
        raise HTTPException(400, "Invalid TRON address")
    try:
        manager.start_task(req.address)
    except AnalysisAlreadyRunning:
        raise HTTPException(409, "An analysis is already running")
    return {"status": "started", "address": req.address}


@router.get("/status")
async def status():
    p = manager.status()
    return {"phase": p.get("phase", "idle"), "percent": p.get("percent", 0)}


@router.get("/overview")
async def overview():
    anchor = store.get_anchor()
    if not anchor:
        raise HTTPException(404, "No analysis available")
    o = store.overview_raw(anchor)
    o["totals"] = {
        "received": _fmt(o["totals"]["received_raw"]),
        "monthly_avg": _fmt(o["totals"]["monthly_avg_raw"]),
    }
    return o


def _monthly_rows(date_from: str | None, date_to: str | None):
    stats = store.read_monthly_stats(date_from, date_to)
    anchor = store.get_anchor()
    months: set[str] = set()
    by_addr: dict[str, dict[str, int]] = {}
    for s in stats:
        months.add(s["year_month"])
        by_addr.setdefault(s["counterparty_address"], {})[s["year_month"]] = s["total_raw"]

    # "You" row — what the anchor received per month.
    you = store.anchor_monthly_raw(anchor) if anchor else {}
    for ym in you:
        if (not date_from or ym >= date_from) and (not date_to or ym <= date_to):
            months.add(ym)

    sorted_months = sorted(months)

    def row(address: str, role: str, cells: dict[str, int]):
        return {
            "address": address,
            "role": role,
            "cells": {ym: _fmt(cells.get(ym, 0)) for ym in sorted_months},
            "total": _fmt(sum(cells.values())),
        }

    rows = [row("You", "anchor", {ym: v for ym, v in you.items() if ym in sorted_months})]
    rows += [
        row(addr, "counterparty", cells)
        for addr, cells in sorted(by_addr.items(), key=lambda kv: -sum(kv[1].values()))
    ]
    return sorted_months, rows


@router.get("/monthly")
async def monthly(from_: str | None = None, to: str | None = None):
    months, rows = _monthly_rows(from_, to)
    return {"months": months, "rows": rows}


@router.get("/graph")
async def graph(month: str | None = None):
    g = store.graph_raw(month)
    return {
        "nodes": g["nodes"],
        "edges": [
            {"source": e["source"], "target": e["target"], "weight": _fmt(e["weight_raw"])}
            for e in g["edges"]
        ],
    }


@router.get("/wallet/{address}")
async def wallet(address: str):
    d = store.wallet_detail_raw(address)
    if d is None:
        raise HTTPException(404, "Unknown wallet")
    for key in ("top_recipients", "top_senders"):
        d[key] = [{"address": x["address"], "total": _fmt(x["total_raw"])} for x in d[key]]
    return d


@router.get("/export/csv")
async def export_csv():
    months, rows = _monthly_rows(None, None)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["counterparty", *months, "total"])
    for r in rows:
        writer.writerow([r["address"], *[r["cells"][m] for m in months], r["total"]])
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=trontrace.csv"},
    )


@router.post("/expand")
async def expand(req: AnalyzeRequest):
    if not _TRON_ADDRESS.match(req.address):
        raise HTTPException(400, "Invalid TRON address")
    try:
        manager.start_expansion_task(req.address)
    except AnalysisAlreadyRunning:
        raise HTTPException(409, "An analysis is already running")
    return {"status": "started", "address": req.address}


@router.get("/cohort")
async def cohort():
    rows = store.read_entity_nodes("recipient")
    return {"recipients": [
        {"address": r["address"], "tier": r["tier"],
         "confidence": r["confidence"], "months_active": r["months_active"],
         "total": _fmt(r["total_raw"])} for r in rows]}


@router.get("/entity-wallets")
async def entity_wallets():
    rows = store.read_entity_nodes("payer")
    return {"wallets": [
        {"address": r["address"], "tier": r["tier"], "confidence": r["confidence"]}
        for r in rows]}
