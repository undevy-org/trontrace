# Entity Expansion & Recurring-Recipient Discovery — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** From a single anchor wallet, discover unknown payer-entity wallets and the full cohort of recurring recipients, confidence-ranked, building on the existing trontrace pipeline.

**Architecture:** A pure scoring module (`expansion_signals.py`) plus an iterative bipartite BFS engine (`expansion.py`) that alternates payee/payer expansion, seeded by the base pipeline's entity cluster, persisting to a new `entity_nodes` table and exposed via new REST endpoints and one frontend screen.

**Tech Stack:** Python 3.11+, FastAPI, SQLite, httpx; React + Vite + TypeScript.

## Global Constraints

- Amounts are integer base units (`amount_raw`); never floats. Convert to decimal strings only at the API/CSV boundary.
- Time is UTC; month buckets are `YYYY-MM`.
- Analysis logic in `app/analysis/` must be pure (no network/DB) and unit-tested.
- All thresholds/weights live in `app/config.py`, environment-overridable.
- Generic public vocabulary only — no "employer/salary/colleague" in code, identifiers, comments, or commit messages. Use payer / recipient / entity / cohort.
- No live TronGrid calls in tests; use `httpx.MockTransport`.
- Run tests from `backend/` with the project venv: `.venv/bin/python -m pytest`.
- End commit messages with: `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`

---

## File Structure

- Create `backend/app/analysis/expansion_signals.py` — pure scoring (fingerprint, recipient_score, payer_score, tier).
- Create `backend/app/expansion.py` — BFS engine `run_expansion`.
- Modify `backend/app/config.py` — expansion params.
- Modify `backend/app/db.py` — `entity_nodes` table.
- Modify `backend/app/store.py` — entity_nodes persistence + read helpers.
- Modify `backend/app/api.py` — `/api/expand`, `/api/cohort`, `/api/entity-wallets`.
- Modify `backend/app/worker.py` — run-mode selection for expansion.
- Create `backend/tests/test_expansion_signals.py`, `backend/tests/test_expansion.py`.
- Create `frontend/src/pages/Cohort.tsx`; modify `frontend/src/api.ts`, `frontend/src/App.tsx`.

---

## Task 1: Pay-cycle fingerprint (pure)

**Files:**
- Create: `backend/app/analysis/expansion_signals.py`
- Modify: `backend/app/config.py`
- Test: `backend/tests/test_expansion_signals.py`

**Interfaces:**
- Produces: `pay_cycle_fingerprint(timestamps: list[int]) -> set[int]`; `aligns_with_cycle(timestamp: int, fingerprint: set[int], tolerance_days: int) -> bool`; config `paycycle_tolerance_days: int`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_expansion_signals.py
from datetime import datetime, timezone
from app.analysis.expansion_signals import pay_cycle_fingerprint, aligns_with_cycle


def _ts(y, m, d):
    return int(datetime(y, m, d, tzinfo=timezone.utc).timestamp())


def test_fingerprint_finds_fixed_pay_days():
    ts = [_ts(2025, m, 1) for m in range(1, 7)] + [_ts(2025, m, 15) for m in range(1, 7)]
    ts += [_ts(2025, 3, 7)]  # one-off noise, should not be a peak
    fp = pay_cycle_fingerprint(ts)
    assert fp == {1, 15}


def test_aligns_within_tolerance():
    fp = {1, 15}
    assert aligns_with_cycle(_ts(2025, 4, 2), fp, tolerance_days=2) is True   # day 2 ~ peak 1
    assert aligns_with_cycle(_ts(2025, 4, 9), fp, tolerance_days=2) is False  # day 9, no peak
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_expansion_signals.py -q`
Expected: FAIL — `ModuleNotFoundError: app.analysis.expansion_signals`.

- [ ] **Step 3: Add config + implement**

In `backend/app/config.py`, add inside `Settings` (after `recipient_fanin_cap`):

```python
    paycycle_tolerance_days: int = 2         # ±days around a pay-date peak
```

Create `backend/app/analysis/expansion_signals.py`:

```python
"""Pure scoring for entity expansion: pay-cycle fingerprint, recipient/payer scores, tiers.

No I/O — fully unit-testable, like similarity.py.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone


def pay_cycle_fingerprint(timestamps: list[int]) -> set[int]:
    """Days-of-month where confirmed payments cluster (the entity's fixed pay dates)."""
    days = [datetime.fromtimestamp(t, tz=timezone.utc).day for t in timestamps]
    if not days:
        return set()
    counts = Counter(days)
    peak = max(counts.values())
    threshold = max(2, peak * 0.5)
    return {d for d, n in counts.items() if n >= threshold}


def aligns_with_cycle(timestamp: int, fingerprint: set[int], tolerance_days: int) -> bool:
    if not fingerprint:
        return False
    day = datetime.fromtimestamp(timestamp, tz=timezone.utc).day
    return any(abs(day - peak) <= tolerance_days for peak in fingerprint)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_expansion_signals.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/app/analysis/expansion_signals.py backend/app/config.py backend/tests/test_expansion_signals.py
git commit -m "feat: pay-cycle fingerprint for entity expansion

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: Recipient score + tier (pure)

**Files:**
- Modify: `backend/app/analysis/expansion_signals.py`
- Modify: `backend/app/config.py`
- Test: `backend/tests/test_expansion_signals.py`

**Interfaces:**
- Consumes: nothing from Task 1 beyond the module.
- Produces: dataclass `RecipientFeatures(n_payers:int, months_paid:int, months_span:int, aligned_fraction:float, amounts:list[int], distinct_senders:int)`; `recipient_score(f: RecipientFeatures) -> float`; `tier(conf: float) -> str`; config `expand_tier_high`, `expand_tier_med`, `corecipient_min_k`, recipient weights.

- [ ] **Step 1: Write the failing test**

```python
# append to backend/tests/test_expansion_signals.py
from app.analysis.expansion_signals import RecipientFeatures, recipient_score, tier


def test_recipient_score_high_for_recurring_lowfanin():
    f = RecipientFeatures(n_payers=2, months_paid=12, months_span=12,
                          aligned_fraction=1.0, amounts=[6000, 6000, 6000], distinct_senders=3)
    assert recipient_score(f) >= 0.8
    assert tier(recipient_score(f)) == "high"


def test_recipient_score_low_for_highfanin_oneoff():
    f = RecipientFeatures(n_payers=1, months_paid=1, months_span=12,
                          aligned_fraction=0.0, amounts=[2_000_000], distinct_senders=400)
    assert recipient_score(f) < 0.45
    assert tier(recipient_score(f)) == "low"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_expansion_signals.py -q`
Expected: FAIL — `ImportError: cannot import name 'RecipientFeatures'`.

- [ ] **Step 3: Add config + implement**

In `backend/app/config.py`, add inside `Settings`:

```python
    expand_tier_high: float = 0.70
    expand_tier_med: float = 0.45
    corecipient_min_k: int = 2               # min known recipients a payer must co-pay (K)
    # recipient score weights (sum 1.0)
    w_rec_corecipient: float = 0.35
    w_rec_recurrence: float = 0.25
    w_rec_paycycle: float = 0.20
    w_rec_stability: float = 0.10
    w_rec_fanin: float = 0.10
```

In `backend/app/analysis/expansion_signals.py`, add at top:

```python
import statistics
from dataclasses import dataclass, field

from ..config import settings
```

Append:

```python
def _recurrence(months_paid: int, months_span: int) -> float:
    if months_span <= 0:
        return 0.0
    return min(1.0, months_paid / months_span)


def _amount_stability(amounts: list[int]) -> float:
    """1 - coefficient of variation, clamped to [0,1]. Stable amounts -> near 1."""
    if len(amounts) < 2:
        return 0.0
    mean = statistics.mean(amounts)
    if mean == 0:
        return 0.0
    cv = statistics.pstdev(amounts) / mean
    return max(0.0, 1.0 - cv)


@dataclass
class RecipientFeatures:
    n_payers: int
    months_paid: int
    months_span: int
    aligned_fraction: float
    amounts: list[int] = field(default_factory=list)
    distinct_senders: int = 0


def recipient_score(f: RecipientFeatures) -> float:
    corec = min(1.0, f.n_payers / max(1, settings.corecipient_min_k))
    rec = _recurrence(f.months_paid, f.months_span)
    align = max(0.0, min(1.0, f.aligned_fraction))
    stab = _amount_stability(f.amounts)
    fanin = 0.0 if f.distinct_senders > settings.recipient_fanin_cap else 1.0
    score = (settings.w_rec_corecipient * corec
             + settings.w_rec_recurrence * rec
             + settings.w_rec_paycycle * align
             + settings.w_rec_stability * stab
             + settings.w_rec_fanin * fanin)
    return min(1.0, score)


def tier(conf: float) -> str:
    if conf >= settings.expand_tier_high:
        return "high"
    if conf >= settings.expand_tier_med:
        return "med"
    return "low"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_expansion_signals.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/app/analysis/expansion_signals.py backend/app/config.py backend/tests/test_expansion_signals.py
git commit -m "feat: recipient score + confidence tiers

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: Payer score + gate (pure)

**Files:**
- Modify: `backend/app/analysis/expansion_signals.py`
- Modify: `backend/app/config.py`
- Test: `backend/tests/test_expansion_signals.py`

**Interfaces:**
- Produces: dataclass `PayerFeatures(overlap_with_cohort:float, n_known_recipients_paid:int, aligned_fraction:float, is_exchange:bool)`; `payer_score(f: PayerFeatures) -> float`; payer weights config.

- [ ] **Step 1: Write the failing test**

```python
# append to backend/tests/test_expansion_signals.py
from app.analysis.expansion_signals import PayerFeatures, payer_score


def test_payer_score_high_when_overlaps_cohort_on_cycle():
    f = PayerFeatures(overlap_with_cohort=0.9, n_known_recipients_paid=3,
                      aligned_fraction=1.0, is_exchange=False)
    assert payer_score(f) >= 0.7


def test_payer_score_zero_below_corroboration_or_exchange():
    below_k = PayerFeatures(overlap_with_cohort=1.0, n_known_recipients_paid=1,
                            aligned_fraction=1.0, is_exchange=False)
    exch = PayerFeatures(overlap_with_cohort=1.0, n_known_recipients_paid=5,
                         aligned_fraction=1.0, is_exchange=True)
    assert payer_score(below_k) == 0.0   # K defaults to 2
    assert payer_score(exch) == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_expansion_signals.py -q`
Expected: FAIL — `ImportError: cannot import name 'PayerFeatures'`.

- [ ] **Step 3: Add config + implement**

In `backend/app/config.py`, add inside `Settings`:

```python
    # payer score weights (sum 1.0)
    w_pay_overlap: float = 0.50
    w_pay_paycycle: float = 0.25
    w_pay_corroboration: float = 0.25
```

In `backend/app/analysis/expansion_signals.py`, append:

```python
@dataclass
class PayerFeatures:
    overlap_with_cohort: float
    n_known_recipients_paid: int
    aligned_fraction: float
    is_exchange: bool = False


def payer_score(f: PayerFeatures) -> float:
    """Hard gate: not an exchange, and co-pays >= K known recipients. Else 0."""
    if f.is_exchange or f.n_known_recipients_paid < settings.corecipient_min_k:
        return 0.0
    corrob = min(1.0, f.n_known_recipients_paid / max(1, settings.corecipient_min_k * 2))
    score = (settings.w_pay_overlap * max(0.0, min(1.0, f.overlap_with_cohort))
             + settings.w_pay_paycycle * max(0.0, min(1.0, f.aligned_fraction))
             + settings.w_pay_corroboration * corrob)
    return min(1.0, score)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_expansion_signals.py -q`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/app/analysis/expansion_signals.py backend/app/config.py backend/tests/test_expansion_signals.py
git commit -m "feat: payer score with corroboration + exchange gate

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: entity_nodes table + store helpers

**Files:**
- Modify: `backend/app/db.py`
- Modify: `backend/app/store.py`
- Test: `backend/tests/test_store.py`

**Interfaces:**
- Produces: `store.upsert_entity_node(address, *, kind, confidence, tier, first_pay=None, last_pay=None, months_active=None, total_raw=None, n_payers=None, discovered_round=None)`; `store.read_entity_nodes(kind: str) -> list[dict]` (ordered by confidence desc).

- [ ] **Step 1: Write the failing test**

```python
# append to backend/tests/test_store.py
def test_entity_nodes_roundtrip_ordered_by_confidence(temp_db):
    store.upsert_entity_node("R1", kind="recipient", confidence=0.9, tier="high",
                             months_active=12, total_raw=72_000000, n_payers=2)
    store.upsert_entity_node("R2", kind="recipient", confidence=0.5, tier="med",
                             months_active=4, total_raw=20_000000, n_payers=1)
    store.upsert_entity_node("W3", kind="payer", confidence=0.8, tier="high")
    recips = store.read_entity_nodes("recipient")
    assert [r["address"] for r in recips] == ["R1", "R2"]   # confidence desc
    assert store.read_entity_nodes("payer")[0]["address"] == "W3"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_store.py -q`
Expected: FAIL — `AttributeError: module 'app.store' has no attribute 'upsert_entity_node'`.

- [ ] **Step 3: Implement**

In `backend/app/db.py`, add to the `SCHEMA` string (before the index block):

```sql
CREATE TABLE IF NOT EXISTS entity_nodes (
    address          TEXT PRIMARY KEY,
    kind             TEXT NOT NULL,     -- 'payer' | 'recipient'
    confidence       REAL,
    tier             TEXT,              -- 'high' | 'med' | 'low'
    first_pay        INTEGER,
    last_pay         INTEGER,
    months_active    INTEGER,
    total_raw        INTEGER,
    n_payers         INTEGER,
    discovered_round INTEGER
);
```

In `backend/app/store.py`, append:

```python
def upsert_entity_node(address, *, kind, confidence, tier, first_pay=None, last_pay=None,
                       months_active=None, total_raw=None, n_payers=None, discovered_round=None):
    with connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO entity_nodes "
            "(address, kind, confidence, tier, first_pay, last_pay, months_active, "
            " total_raw, n_payers, discovered_round) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (address, kind, confidence, tier, first_pay, last_pay, months_active,
             total_raw, n_payers, discovered_round),
        )


def read_entity_nodes(kind: str) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM entity_nodes WHERE kind = ? ORDER BY confidence DESC, address",
            (kind,),
        ).fetchall()
    return [dict(r) for r in rows]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_store.py -q`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/app/db.py backend/app/store.py backend/tests/test_store.py
git commit -m "feat: entity_nodes table + store helpers

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: Expansion BFS engine

**Files:**
- Create: `backend/app/expansion.py`
- Test: `backend/tests/test_expansion.py`

**Interfaces:**
- Consumes: `expansion_signals.*`, `store.*`, `classify.is_exchange_recipient`, `trongrid.TronGridClient`.
- Produces: `async run_expansion(anchor: str, client: TronGridClient, seed_payers: set[str] | None = None) -> None` — persists `entity_nodes` (kind payer/recipient) and `monthly_stats` for the cohort.

This engine alternates: (payee step) fetch each payer's outbound → score recipients; (payer step) fetch each new recipient's inbound → score senders as candidate payers. Loop until no High/Med node is added or caps hit.

- [ ] **Step 1: Write the failing integration test**

```python
# backend/tests/test_expansion.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_expansion.py -q`
Expected: FAIL — `ModuleNotFoundError: app.expansion`.

- [ ] **Step 3: Implement the engine**

Create `backend/app/expansion.py`:

```python
"""Iterative bipartite expansion engine (payers <-> recurring recipients).

Seeds from the base pipeline's entity wallets, then alternates:
  payee step  — score each payer's recipients, add cohort members
  payer step  — score each recipient's senders, discover new entity wallets
Loops until no High/Med node is added (loop-until-dry) or caps are hit.
"""
from __future__ import annotations

from . import store
from .analysis import expansion_signals as sig
from .analysis.classify import is_exchange_recipient
from .analysis.monthly import Transfer, aggregate_monthly, year_month_utc
from .config import settings
from .trongrid import TronGridClient


async def run_expansion(
    anchor: str, client: TronGridClient, seed_payers: set[str] | None = None
) -> None:
    store.set_progress(anchor=anchor, phase="expand", percent=0)
    payers: set[str] = set(seed_payers if seed_payers is not None
                           else store.get_wallets_by_role("primary_payer"))
    cohort: set[str] = {anchor}
    payer_frontier = set(payers)
    recipient_frontier: set[str] = set()
    rounds = 0

    while (payer_frontier or recipient_frontier) and rounds < settings.expand_max_rounds:
        rounds += 1

        # --- payee step: payers -> candidate recipients ---
        new_recipients: set[str] = set()
        for w in list(payer_frontier):
            res = await client.fetch_transfers(w, direction="out",
                                               max_records=settings.candidate_tx_cap)
            store.insert_transactions(res.records)
        payer_frontier.clear()

        fingerprint = _fingerprint(payers, anchor)
        for cand in _recipients_of(payers) - cohort - {anchor}:
            feats, _ = _recipient_features(cand, payers, fingerprint, client_cache=None)
            conf = sig.recipient_score(feats)
            t = sig.tier(conf)
            _persist_recipient(cand, conf, t, feats)
            if t in ("high", "med"):
                cohort.add(cand)
                new_recipients.add(cand)
        recipient_frontier = new_recipients

        # --- payer step: recipients -> candidate payers ---
        new_payers: set[str] = set()
        for r in list(recipient_frontier):
            res = await client.fetch_transfers(r, direction="in",
                                               max_records=settings.recipient_inbound_cap)
            store.insert_transactions(res.records)

        fingerprint = _fingerprint(payers, anchor)
        for cand in _senders_to(cohort) - payers - {anchor}:
            feats = _payer_features(cand, cohort, fingerprint)
            conf = sig.payer_score(feats)
            t = sig.tier(conf)
            if conf > 0:
                store.upsert_entity_node(cand, kind="payer", confidence=conf, tier=t,
                                         discovered_round=rounds)
            if t in ("high", "med") and len(payers) < settings.expand_max_payers:
                payers.add(cand)
                new_payers.add(cand)
        payer_frontier = new_payers

    _write_cohort_timelines(payers, cohort, anchor)
    store.set_progress(phase="done", percent=100)


def _recipients_of(payers: set[str]) -> set[str]:
    out: set[str] = set()
    for w in payers:
        out |= store.get_recipients(w)
    return out


def _senders_to(cohort: set[str]) -> set[str]:
    out: set[str] = set()
    for r in cohort:
        out |= store.get_funding_sources(r)
    return out


def _fingerprint(payers: set[str], anchor: str) -> set[int]:
    ts: list[int] = []
    for _to, _amt, t in store.outbound_transfers(payers):
        ts.append(t)
    return sig.pay_cycle_fingerprint(ts)


def _recipient_features(addr, payers, fingerprint, client_cache):
    rows = [(f, a, t) for (f, a, t) in _inbound_rows(addr)]
    senders = {f for f, _a, _t in rows}
    from_payers = [(a, t) for f, a, t in rows if f in payers]
    n_payers = len({f for f, _a, _t in rows if f in payers})
    months = {year_month_utc(t) for _a, t in from_payers}
    span_months = _month_span(addr, payers)
    aligned = ([sig.aligns_with_cycle(t, fingerprint, settings.paycycle_tolerance_days)
                for _a, t in from_payers])
    aligned_fraction = (sum(aligned) / len(aligned)) if aligned else 0.0
    feats = sig.RecipientFeatures(
        n_payers=n_payers, months_paid=len(months), months_span=span_months,
        aligned_fraction=aligned_fraction, amounts=[a for a, _t in from_payers],
        distinct_senders=len(senders))
    return feats, rows


def _payer_features(addr, cohort, fingerprint):
    recips = store.get_recipients(addr)
    paid_known = recips & cohort
    overlap = (len(paid_known) / min(len(recips), len(cohort))) if recips and cohort else 0.0
    out_ts = [t for _to, _a, t in store.outbound_transfers({addr})]
    aligned = [sig.aligns_with_cycle(t, fingerprint, settings.paycycle_tolerance_days)
               for t in out_ts]
    aligned_fraction = (sum(aligned) / len(aligned)) if aligned else 0.0
    is_exch = is_exchange_recipient(addr, distinct_senders=len(store.get_funding_sources(addr)))
    return sig.PayerFeatures(overlap_with_cohort=overlap,
                             n_known_recipients_paid=len(paid_known),
                             aligned_fraction=aligned_fraction, is_exchange=is_exch)


def _inbound_rows(addr):
    from .db import connect
    with connect() as conn:
        return conn.execute(
            "SELECT from_address, amount_raw, timestamp FROM transactions WHERE to_address = ?",
            (addr,)).fetchall()


def _month_span(addr, payers):
    ts = [t for f, _a, t in _inbound_rows(addr) if f in payers]
    if not ts:
        return 0
    lo, hi = min(ts), max(ts)
    from datetime import datetime, timezone
    a = datetime.fromtimestamp(lo, tz=timezone.utc)
    b = datetime.fromtimestamp(hi, tz=timezone.utc)
    return (b.year - a.year) * 12 + (b.month - a.month) + 1


def _persist_recipient(addr, conf, t, feats):
    store.upsert_entity_node(addr, kind="recipient", confidence=conf, tier=t,
                             months_active=feats.months_paid, n_payers=feats.n_payers,
                             total_raw=sum(feats.amounts))


def _write_cohort_timelines(payers, cohort, anchor):
    transfers = [Transfer(to, amt, ts)
                 for (to, amt, ts) in store.outbound_transfers(payers)
                 if to in cohort]
    store.write_monthly_stats(aggregate_monthly(transfers))
```

- [ ] **Step 4: Add the remaining config caps**

In `backend/app/config.py`, add inside `Settings`:

```python
    expand_max_rounds: int = 6
    expand_max_payers: int = 200
    expand_max_recipients: int = 5000
    expand_max_total_fetches: int = 4000
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_expansion.py -q`
Expected: PASS (1 passed). If `R2`/`R3` miss the cohort, confirm tier thresholds in config match Task 2.

- [ ] **Step 6: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS (all previous + new).

- [ ] **Step 7: Commit**

```bash
git add backend/app/expansion.py backend/app/config.py backend/tests/test_expansion.py
git commit -m "feat: iterative bipartite expansion engine

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: REST API + worker wiring

**Files:**
- Modify: `backend/app/worker.py`
- Modify: `backend/app/api.py`
- Test: `backend/tests/test_api.py`

**Interfaces:**
- Consumes: `run_expansion`, `store.read_entity_nodes`.
- Produces: `POST /api/expand`, `GET /api/cohort`, `GET /api/entity-wallets`; `AnalysisManager.start_expansion_task(anchor)`.

- [ ] **Step 1: Write the failing test**

```python
# append to backend/tests/test_api.py
def test_cohort_and_entity_wallets_endpoints(temp_db):
    store.upsert_entity_node("R1", kind="recipient", confidence=0.9, tier="high",
                             months_active=12, total_raw=72_000000, n_payers=2)
    store.upsert_entity_node("W3", kind="payer", confidence=0.8, tier="high")
    client = TestClient(app)
    cohort = client.get("/api/cohort").json()
    assert cohort["recipients"][0]["address"] == "R1"
    assert cohort["recipients"][0]["total"] == "72"      # decimal-formatted
    wallets = client.get("/api/entity-wallets").json()
    assert wallets["wallets"][0]["address"] == "W3"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_api.py -q`
Expected: FAIL — 404 on `/api/cohort`.

- [ ] **Step 3: Implement worker + routes**

In `backend/app/worker.py`, add to `AnalysisManager` (after `start_task`):

```python
    def start_expansion_task(self, anchor: str):
        if self.is_running():
            raise AnalysisAlreadyRunning()
        import asyncio
        from .expansion import run_expansion

        async def _run():
            async with self._factory() as client:
                await run_expansion(anchor, client)

        self._task = asyncio.create_task(_run())
        return self._task
```

In `backend/app/api.py`, add routes:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_api.py -q`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS (all).

- [ ] **Step 6: Commit**

```bash
git add backend/app/worker.py backend/app/api.py backend/tests/test_api.py
git commit -m "feat: expansion API endpoints + worker wiring

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 7: Frontend cohort screen

**Files:**
- Modify: `frontend/src/api.ts`
- Create: `frontend/src/pages/Cohort.tsx`
- Modify: `frontend/src/App.tsx`

**Interfaces:**
- Consumes: `/api/cohort`.
- Produces: a `Cohort` route at `/cohort`.

- [ ] **Step 1: Add the API method**

In `frontend/src/api.ts`, add the interface and method:

```typescript
export interface Cohort {
  recipients: { address: string; tier: string; confidence: number; months_active: number; total: string }[];
}
```

Inside the `api` object, add:

```typescript
  cohort: () => get<Cohort>("/cohort"),
```

- [ ] **Step 2: Create the screen**

Create `frontend/src/pages/Cohort.tsx`:

```tsx
import { useEffect, useState } from "react";
import { api, Cohort as CohortData } from "../api";
import { WalletDetail } from "../components/WalletDetail";

const TIER_COLOR: Record<string, string> = { high: "#2e7d32", med: "#f9a825", low: "#9e9e9e" };

export function Cohort() {
  const [data, setData] = useState<CohortData | null>(null);
  const [selected, setSelected] = useState<string | null>(null);

  useEffect(() => {
    api.cohort().then(setData).catch(() => setData(null));
  }, []);

  if (!data) return <p>No expansion yet. Run one from the home screen.</p>;

  return (
    <section>
      <h1>Recurring-recipient cohort</h1>
      <blockquote>Heuristic estimates from public on-chain data, not verified facts.</blockquote>
      <table style={{ borderCollapse: "collapse", width: "100%" }}>
        <thead>
          <tr>
            <th style={{ textAlign: "left", padding: 6 }}>Address</th>
            <th style={{ padding: 6 }}>Tier</th>
            <th style={{ padding: 6 }}>Months</th>
            <th style={{ padding: 6 }}>Total</th>
          </tr>
        </thead>
        <tbody>
          {data.recipients.map((r) => (
            <tr key={r.address}>
              <td style={{ padding: 6 }}>
                <button onClick={() => setSelected(r.address)}
                        style={{ background: "none", border: 0, color: "#1565c0", cursor: "pointer" }}>
                  {r.address}
                </button>
              </td>
              <td style={{ padding: 6, textAlign: "center" }}>
                <span style={{ color: TIER_COLOR[r.tier] ?? "#777" }}>{r.tier}</span>
              </td>
              <td style={{ padding: 6, textAlign: "center" }}>{r.months_active}</td>
              <td style={{ padding: 6, textAlign: "right" }}>{r.total}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {selected && <WalletDetail address={selected} onClose={() => setSelected(null)} />}
    </section>
  );
}
```

- [ ] **Step 3: Wire the route**

In `frontend/src/App.tsx`, add the import:

```tsx
import { Cohort } from "./pages/Cohort";
```

Add a nav link after the Graph link:

```tsx
<Link to="/cohort">Cohort</Link>
```

Add a route inside `<Routes>`:

```tsx
<Route path="/cohort" element={<Cohort />} />
```

- [ ] **Step 4: Verify the build**

Run: `cd frontend && npm run build`
Expected: `tsc` passes and `vite build` succeeds (no type errors).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api.ts frontend/src/pages/Cohort.tsx frontend/src/App.tsx
git commit -m "feat: cohort screen for recurring recipients

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 8: Calibration on a real anchor (manual)

**Files:** none (operational). Produces tuned config values, committed if changed.

- [ ] **Step 1: Run expansion against a real anchor**

Start the backend, then:

```bash
curl -s -X POST http://localhost:8000/api/expand -H "Content-Type: application/json" \
  -d '{"address":"<ANCHOR>"}'
# poll until done
curl -s http://localhost:8000/api/status
```

- [ ] **Step 2: Inspect tiers**

```bash
curl -s http://localhost:8000/api/cohort | python3 -m json.tool | head -40
curl -s http://localhost:8000/api/entity-wallets | python3 -m json.tool
```

- [ ] **Step 3: Spot-check on a block explorer**

Pick 5 High-tier recipients and 3 discovered payers; verify on Tronscan that the payers co-pay the same recipients on the pay-cycle dates. Record any false positives/negatives.

- [ ] **Step 4: Tune and (if changed) commit**

Adjust `expand_tier_high`, `expand_tier_med`, `corecipient_min_k`, `paycycle_tolerance_days`, or signal weights in `.env` / `config.py` defaults to match observed precision. If you change `config.py` defaults:

```bash
git add backend/app/config.py
git commit -m "chore: calibrate expansion thresholds from real run

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review Notes

- **Spec coverage:** seed (T5), payee/payer steps (T5), loop-until-dry + caps (T5 config), pay-cycle fingerprint (T1), recipient/payer scoring + tiers (T2/T3), drift gate ≥K + exchange (T3/T5), entity_nodes + timelines (T4/T5), API (T6), frontend screen (T7), calibration (T8). Error handling/checkpoint reuse the base infra already covered by `trongrid`/`store`.
- **Generic vocabulary:** all identifiers use payer/recipient/entity/cohort.
- **Type consistency:** `RecipientFeatures`/`PayerFeatures` fields and `recipient_score`/`payer_score`/`tier`/`run_expansion` signatures are identical across tasks and usage.
