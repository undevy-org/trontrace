# Consistent-Amount Recipient Ranking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make amount consistency the dominant recipient signal, and add a filterable view that ranks fixed-amount recurring recipients with wallet-change hints.

**Architecture:** Re-weight the existing `recipient_score`; add a pure `consistency.py` module (`consistent_rows`, `wallet_change_hints`); a store helper to read cohort monthly series; a `/api/consistent` endpoint deriving results on read from `monthly_stats`; and a `/consistent` frontend screen.

**Tech Stack:** Python 3.11+, FastAPI, SQLite, httpx; React + Vite + TypeScript.

## Global Constraints

- Amounts are integer base units (`amount_raw`); never floats. Decimal strings only at the API/CSV boundary via the existing `_fmt` helper.
- Time is UTC; month buckets are `YYYY-MM`.
- Analysis modules (`app/analysis/`) must be pure (no network/DB) and unit-tested.
- All thresholds/weights/caps live in `app/config.py`, environment-overridable.
- Generic public vocabulary only — payer/recipient/entity/cohort/consistent; NO employer/salary/colleague in identifiers, comments, or commit messages.
- No live TronGrid calls in tests; use `httpx.MockTransport` / seeded SQLite via the `temp_db` fixture.
- Run tests from `backend/` with the project venv: `.venv/bin/python -m pytest`.
- End commit messages with: `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`

---

## File Structure
- Modify `backend/app/analysis/expansion_signals.py` — expose `amount_consistency`; re-weight `recipient_score`.
- Modify `backend/app/config.py` — re-weighted `w_rec_*` defaults; new `consistent_*` params.
- Create `backend/app/analysis/consistency.py` — `ConsistentRow`, `consistent_rows`, `wallet_change_hints`.
- Modify `backend/app/store.py` — `cohort_timelines()` read helper.
- Modify `backend/app/api.py` — `GET /api/consistent`.
- Create `backend/tests/test_consistency.py`; modify `backend/tests/test_expansion_signals.py`, `backend/tests/test_store.py`, `backend/tests/test_api.py`.
- Create `frontend/src/pages/Consistent.tsx`; modify `frontend/src/api.ts`, `frontend/src/App.tsx`.

---

## Task 1: Expose `amount_consistency` + re-weight recipient score

**Files:**
- Modify: `backend/app/analysis/expansion_signals.py`
- Modify: `backend/app/config.py`
- Test: `backend/tests/test_expansion_signals.py`

**Interfaces:**
- Produces: `amount_consistency(values: list[int]) -> float` (public); re-weighted `recipient_score` defaults.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_expansion_signals.py`:

```python
from app.analysis.expansion_signals import amount_consistency


def test_amount_consistency_identical_and_variable():
    assert amount_consistency([6000, 6000, 6000]) >= 0.99   # identical -> ~1
    assert amount_consistency([1000, 11000, 1000, 11000]) < 0.5   # high variance -> low
    assert amount_consistency([6000]) == 0.0                # <2 points -> 0


def test_consistent_amount_outranks_variable():
    from app.analysis.expansion_signals import RecipientFeatures, recipient_score, tier
    base = dict(n_payers=2, months_paid=12, aligned_fraction=1.0, distinct_senders=3)
    steady = RecipientFeatures(amounts=[6000] * 12, **base)
    variable = RecipientFeatures(amounts=[1000, 11000] * 6, **base)   # same mean, high variance
    assert recipient_score(steady) > recipient_score(variable)
    assert tier(recipient_score(steady)) == "high"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_expansion_signals.py -q`
Expected: FAIL — `ImportError: cannot import name 'amount_consistency'`.

- [ ] **Step 3: Rename + re-weight**

In `backend/app/analysis/expansion_signals.py`, rename the private `_amount_stability` to a public `amount_consistency` (same body) and update its call site inside `recipient_score`:

```python
def amount_consistency(values: list[int]) -> float:
    """1 - coefficient of variation, clamped to [0,1]. Identical values -> ~1; needs >=2 points."""
    if len(values) < 2:
        return 0.0
    mean = statistics.mean(values)
    if mean == 0:
        return 0.0
    cv = statistics.pstdev(values) / mean
    return max(0.0, 1.0 - cv)
```

In `recipient_score`, change the stability line to:

```python
    stab = amount_consistency(f.amounts)
```

In `backend/app/config.py`, change the recipient-score weight defaults to make consistency dominant (sum stays 1.0):

```python
    w_rec_corecipient: float = 0.25
    w_rec_recurrence: float = 0.20
    w_rec_paycycle: float = 0.10
    w_rec_stability: float = 0.40   # multiplies amount_consistency (dominant)
    w_rec_fanin: float = 0.05
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_expansion_signals.py -q`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS (existing recipient/expansion tests still green under the new weights; if a prior test asserted an exact score that changed, update it to assert the documented behavior, not a magic number).

- [ ] **Step 6: Commit**

```bash
git add backend/app/analysis/expansion_signals.py backend/app/config.py backend/tests/test_expansion_signals.py
git commit -m "feat: amount consistency as dominant recipient signal

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: `consistent_rows` (pure)

**Files:**
- Create: `backend/app/analysis/consistency.py`
- Modify: `backend/app/config.py`
- Test: `backend/tests/test_consistency.py`

**Interfaces:**
- Consumes: `amount_consistency` from Task 1.
- Produces: dataclass `ConsistentRow(address:str, median_monthly:int, months_paid:int, consistency:float)`; `consistent_rows(timelines: dict[str, list[tuple[str,int]]], *, band_low, band_high, min_consistency, min_months) -> list[ConsistentRow]`; config `consistent_band_low`, `consistent_band_high`, `consistent_min_consistency`, `consistent_min_months`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_consistency.py`:

```python
from app.analysis.consistency import ConsistentRow, consistent_rows

M = 1_000_000  # 1 USDT in base units


def _series(start_month, amounts):
    return [(f"2025-{start_month + i:02d}", a) for i, a in enumerate(amounts)]


def test_consistent_rows_filters_and_sorts():
    timelines = {
        "STEADY": _series(1, [3000 * M] * 6),                 # consistent, in band -> keep
        "BIG":    _series(1, [50000 * M] * 6),                # above band -> drop
        "ONEOFF": _series(1, [3000 * M]),                     # < min_months -> drop
        "NOISY":  _series(1, [1000 * M, 11000 * M] * 3),      # low consistency -> drop
        "SMALL":  _series(1, [2000 * M] * 6),                 # consistent, in band -> keep
    }
    rows = consistent_rows(timelines, band_low=500 * M, band_high=12000 * M,
                           min_consistency=0.80, min_months=4)
    assert [r.address for r in rows] == ["STEADY", "SMALL"]   # sorted by amount desc
    assert rows[0].median_monthly == 3000 * M
    assert rows[0].months_paid == 6
    assert rows[0].consistency >= 0.99
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_consistency.py -q`
Expected: FAIL — `ModuleNotFoundError: app.analysis.consistency`.

- [ ] **Step 3: Implement**

In `backend/app/config.py`, add:

```python
    consistent_band_low: int = 500_000000        # base units (~$500)
    consistent_band_high: int = 12000_000000     # base units (~$12000)
    consistent_min_consistency: float = 0.80
    consistent_min_months: int = 4
```

Create `backend/app/analysis/consistency.py`:

```python
"""Fixed-amount recurring-recipient ranking (pure, no I/O).

Ranks recipients by how consistently they receive the same monthly amount, and flags likely
wallet-change pairs. Operates on monthly series read elsewhere; this module stays pure.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass

from .expansion_signals import amount_consistency


@dataclass
class ConsistentRow:
    address: str
    median_monthly: int
    months_paid: int
    consistency: float


def consistent_rows(
    timelines: dict[str, list[tuple[str, int]]],
    *,
    band_low: int,
    band_high: int,
    min_consistency: float,
    min_months: int,
) -> list[ConsistentRow]:
    """Keep recipients with a stable monthly amount in band; sort by amount descending."""
    out: list[ConsistentRow] = []
    for address, series in timelines.items():
        amounts = [amt for _ym, amt in series]
        if len(amounts) < min_months:
            continue
        median = int(statistics.median(amounts))
        if not (band_low <= median <= band_high):
            continue
        cons = amount_consistency(amounts)
        if cons < min_consistency:
            continue
        out.append(ConsistentRow(address, median, len(amounts), cons))
    out.sort(key=lambda r: -r.median_monthly)
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_consistency.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/analysis/consistency.py backend/app/config.py backend/tests/test_consistency.py
git commit -m "feat: consistent_rows ranking for fixed-amount recipients

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: `wallet_change_hints` (pure)

**Files:**
- Modify: `backend/app/analysis/consistency.py`
- Modify: `backend/app/config.py`
- Test: `backend/tests/test_consistency.py`

**Interfaces:**
- Consumes: `ConsistentRow` from Task 2.
- Produces: `wallet_change_hints(rows: list[ConsistentRow], timelines: dict[str, list[tuple[str,int]]]) -> list[tuple[str,str,str]]`; config `consistent_change_amount_tol`, `consistent_change_max_gap_months`.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_consistency.py`:

```python
from app.analysis.consistency import wallet_change_hints


def test_wallet_change_hint_flags_adjacent_equal_amount():
    rows = [ConsistentRow("A", 3000 * M, 5, 0.95), ConsistentRow("B", 3000 * M, 4, 0.95)]
    timelines = {
        "A": _series(1, [3000 * M] * 5),   # 2025-01..2025-05
        "B": _series(6, [3000 * M] * 4),   # 2025-06..2025-09  (adjacent, no overlap)
    }
    hints = wallet_change_hints(rows, timelines)
    assert [(h[0], h[1]) for h in hints] == [("A", "B")]


def test_no_hint_for_overlap_or_different_amount():
    rows = [ConsistentRow("A", 3000 * M, 5, 0.95), ConsistentRow("C", 9000 * M, 5, 0.95),
            ConsistentRow("D", 3000 * M, 5, 0.95)]
    timelines = {
        "A": _series(1, [3000 * M] * 5),    # 2025-01..05
        "C": _series(6, [9000 * M] * 5),    # adjacent but different amount -> no hint
        "D": _series(3, [3000 * M] * 5),    # same amount but overlaps A -> no hint
    }
    assert wallet_change_hints(rows, timelines) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_consistency.py -q`
Expected: FAIL — `ImportError: cannot import name 'wallet_change_hints'`.

- [ ] **Step 3: Implement**

In `backend/app/config.py`, add:

```python
    consistent_change_amount_tol: float = 0.10    # max relative amount difference for a hint
    consistent_change_max_gap_months: int = 1     # max month-hole between adjacent ranges
```

Append to `backend/app/analysis/consistency.py`:

```python
from ..config import settings


def _months_between(end_ym: str, start_ym: str) -> int:
    ey, em = (int(x) for x in end_ym.split("-"))
    sy, sm = (int(x) for x in start_ym.split("-"))
    return (sy - ey) * 12 + (sm - em)


def wallet_change_hints(
    rows: list[ConsistentRow], timelines: dict[str, list[tuple[str, int]]]
) -> list[tuple[str, str, str]]:
    """Flag (earlier, later, reason) pairs with ~equal amount and adjacent, non-overlapping months."""
    by_addr = {r.address: r for r in rows}
    ranges = {a: (min(ym for ym, _ in s), max(ym for ym, _ in s)) for a, s in timelines.items()}
    addrs = [r.address for r in rows]
    hints: list[tuple[str, str, str]] = []
    for a in addrs:
        for b in addrs:
            if a == b or a not in ranges or b not in ranges:
                continue
            ma, mb = by_addr[a].median_monthly, by_addr[b].median_monthly
            if max(ma, mb) == 0 or abs(ma - mb) / max(ma, mb) > settings.consistent_change_amount_tol:
                continue
            a_hi, b_lo = ranges[a][1], ranges[b][0]
            step = _months_between(a_hi, b_lo)        # >=1 means b starts after a ends
            if step >= 1 and (step - 1) <= settings.consistent_change_max_gap_months:
                hints.append((a, b, "same amount, adjacent months"))
    return hints
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_consistency.py -q`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/analysis/consistency.py backend/app/config.py backend/tests/test_consistency.py
git commit -m "feat: wallet-change hints for likely same-entity address pairs

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: `cohort_timelines` store helper

**Files:**
- Modify: `backend/app/store.py`
- Test: `backend/tests/test_store.py`

**Interfaces:**
- Produces: `cohort_timelines() -> dict[str, list[tuple[str, int]]]` — address → sorted list of `(year_month, total_raw)` from `monthly_stats`.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_store.py`:

```python
def test_cohort_timelines_groups_by_address(temp_db):
    from app.analysis.monthly import MonthlyCell
    store.write_monthly_stats([
        MonthlyCell("R1", "2025-01", 3_000000, 1),
        MonthlyCell("R1", "2025-02", 3_000000, 1),
        MonthlyCell("R2", "2025-01", 5_000000, 1),
    ])
    tl = store.cohort_timelines()
    assert tl["R1"] == [("2025-01", 3_000000), ("2025-02", 3_000000)]
    assert tl["R2"] == [("2025-01", 5_000000)]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_store.py -q`
Expected: FAIL — `AttributeError: module 'app.store' has no attribute 'cohort_timelines'`.

- [ ] **Step 3: Implement**

Append to `backend/app/store.py`:

```python
def cohort_timelines() -> dict[str, list[tuple[str, int]]]:
    """address -> sorted [(year_month, total_raw)] from monthly_stats."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT counterparty_address, year_month, total_raw FROM monthly_stats "
            "ORDER BY counterparty_address, year_month"
        ).fetchall()
    out: dict[str, list[tuple[str, int]]] = {}
    for addr, ym, raw in rows:
        out.setdefault(addr, []).append((ym, raw))
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_store.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/store.py backend/tests/test_store.py
git commit -m "feat: cohort_timelines store helper

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: `GET /api/consistent` endpoint

**Files:**
- Modify: `backend/app/api.py`
- Test: `backend/tests/test_api.py`

**Interfaces:**
- Consumes: `store.cohort_timelines`, `consistent_rows`, `wallet_change_hints`, `_fmt`, `settings`.
- Produces: `GET /api/consistent?band_low=&band_high=&min_consistency=&min_months=` → `{ rows: [{address, amount, months, consistency}], hints: [{a, b, reason}] }`.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_api.py`:

```python
def test_consistent_endpoint(temp_db):
    from app.analysis.monthly import MonthlyCell
    from app import store
    cells = [MonthlyCell("A", f"2025-{m:02d}", 3_000000, 1) for m in range(1, 6)]
    cells += [MonthlyCell("B", f"2025-{m:02d}", 3_000000, 1) for m in range(6, 10)]
    cells += [MonthlyCell("BIG", f"2025-{m:02d}", 50000_000000, 1) for m in range(1, 6)]
    store.write_monthly_stats(cells)
    client = TestClient(app)
    data = client.get("/api/consistent?band_low=500000000&band_high=12000000000"
                      "&min_consistency=0.8&min_months=4").json()
    addrs = {r["address"] for r in data["rows"]}
    assert addrs == {"A", "B"}                      # BIG dropped by band
    assert data["rows"][0]["amount"] == "3"         # decimal-formatted
    assert ["A", "B"] in [[h["a"], h["b"]] for h in data["hints"]]   # adjacent equal-amount pair
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_api.py -q`
Expected: FAIL — 404 on `/api/consistent`.

- [ ] **Step 3: Implement**

In `backend/app/api.py`, add the import near the top:

```python
from .analysis.consistency import consistent_rows, wallet_change_hints
```

Add the route:

```python
@router.get("/consistent")
async def consistent(band_low: int | None = None, band_high: int | None = None,
                     min_consistency: float | None = None, min_months: int | None = None):
    timelines = store.cohort_timelines()
    rows = consistent_rows(
        timelines,
        band_low=band_low if band_low is not None else settings.consistent_band_low,
        band_high=band_high if band_high is not None else settings.consistent_band_high,
        min_consistency=min_consistency if min_consistency is not None else settings.consistent_min_consistency,
        min_months=min_months if min_months is not None else settings.consistent_min_months,
    )
    hints = wallet_change_hints(rows, timelines)
    return {
        "rows": [
            {"address": r.address, "amount": _fmt(r.median_monthly),
             "months": r.months_paid, "consistency": round(r.consistency, 2)}
            for r in rows
        ],
        "hints": [{"a": a, "b": b, "reason": reason} for a, b, reason in hints],
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_api.py -q`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS (all).

- [ ] **Step 6: Commit**

```bash
git add backend/app/api.py backend/tests/test_api.py
git commit -m "feat: /api/consistent endpoint

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: `/consistent` frontend screen

**Files:**
- Modify: `frontend/src/api.ts`
- Create: `frontend/src/pages/Consistent.tsx`
- Modify: `frontend/src/App.tsx`

**Interfaces:**
- Consumes: `/api/consistent`.
- Produces: a `Consistent` route at `/consistent`.

- [ ] **Step 1: Add the API types + method**

In `frontend/src/api.ts`, add the interface:

```typescript
export interface Consistent {
  rows: { address: string; amount: string; months: number; consistency: number }[];
  hints: { a: string; b: string; reason: string }[];
}
```

Inside the `api` object, add:

```typescript
  consistent: (params = "") => get<Consistent>(`/consistent${params}`),
```

- [ ] **Step 2: Create the screen**

Create `frontend/src/pages/Consistent.tsx`:

```tsx
import { useEffect, useMemo, useState } from "react";
import { api, Consistent as Data } from "../api";
import { WalletDetail } from "../components/WalletDetail";

export function Consistent() {
  const [data, setData] = useState<Data | null>(null);
  const [minMonths, setMinMonths] = useState("4");
  const [minCons, setMinCons] = useState("0.8");
  const [selected, setSelected] = useState<string | null>(null);

  useEffect(() => {
    const q = `?min_months=${minMonths || 0}&min_consistency=${minCons || 0}`;
    api.consistent(q).then(setData).catch(() => setData(null));
  }, [minMonths, minCons]);

  const partners = useMemo(() => {
    const m = new Map<string, string>();
    data?.hints.forEach((h) => { m.set(h.a, h.b); m.set(h.b, h.a); });
    return m;
  }, [data]);

  function downloadCsv() {
    if (!data) return;
    const lines = [["address", "amount_per_month", "months", "consistency"].join(",")];
    data.rows.forEach((r) => lines.push([r.address, r.amount, r.months, r.consistency].join(",")));
    const url = URL.createObjectURL(new Blob([lines.join("\n")], { type: "text/csv" }));
    const a = document.createElement("a");
    a.href = url; a.download = "consistent-recipients.csv"; a.click();
    URL.revokeObjectURL(url);
  }

  if (!data) return <p>No analysis yet. Run an expansion first.</p>;

  return (
    <section>
      <h1>Consistent-amount recipients</h1>
      <blockquote>Heuristic estimate from public on-chain data, not verified facts.</blockquote>
      <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
        <label>min months <input value={minMonths} onChange={(e) => setMinMonths(e.target.value)} style={{ width: 50 }} /></label>
        <label>min consistency <input value={minCons} onChange={(e) => setMinCons(e.target.value)} style={{ width: 50 }} /></label>
        <button onClick={downloadCsv}>Export CSV</button>
      </div>
      <table style={{ borderCollapse: "collapse", width: "100%" }}>
        <thead><tr>
          <th style={{ textAlign: "left", padding: 6 }}>Address</th>
          <th style={{ padding: 6 }}>Amount/mo</th>
          <th style={{ padding: 6 }}>Months</th>
          <th style={{ padding: 6 }}>Consistency</th>
        </tr></thead>
        <tbody>
          {data.rows.map((r) => (
            <tr key={r.address}>
              <td style={{ padding: 6 }}>
                <button onClick={() => setSelected(r.address)}
                        style={{ background: "none", border: 0, color: "#1565c0", cursor: "pointer" }}>
                  {r.address}
                </button>
                {partners.has(r.address) && (
                  <span title={`possible same entity as ${partners.get(r.address)}`}
                        style={{ marginLeft: 6, fontSize: 11, color: "#8e24aa" }}>↔</span>
                )}
              </td>
              <td style={{ padding: 6, textAlign: "right" }}>{r.amount}</td>
              <td style={{ padding: 6, textAlign: "center" }}>{r.months}</td>
              <td style={{ padding: 6, textAlign: "center" }}>{Math.round(r.consistency * 100)}%</td>
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
import { Consistent } from "./pages/Consistent";
```

Add a nav link after the Cohort link:

```tsx
<Link to="/consistent">Consistent</Link>
```

Add a route inside `<Routes>`:

```tsx
<Route path="/consistent" element={<Consistent />} />
```

- [ ] **Step 4: Verify the build**

Run: `cd frontend && npm run build`
Expected: `tsc` passes and `vite build` succeeds.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api.ts frontend/src/pages/Consistent.tsx frontend/src/App.tsx
git commit -m "feat: consistent-amount recipients screen

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review Notes
- **Spec coverage:** core re-weight (T1), `consistent_rows` + config (T2), `wallet_change_hints` + config (T3), timelines read helper (T4), `/api/consistent` (T5), `/consistent` screen + hint badge + filters + client-side CSV export (T6). All spec sections mapped.
- **Generic vocabulary:** identifiers use payer/recipient/entity/cohort/consistent.
- **Type consistency:** `ConsistentRow` fields and `amount_consistency`/`consistent_rows`/`wallet_change_hints`/`cohort_timelines` signatures match across tasks and call sites.
