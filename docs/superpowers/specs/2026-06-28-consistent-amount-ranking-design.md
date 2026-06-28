# Consistent-Amount Recipient Ranking — Design Spec

**Date:** 2026-06-28
**Status:** Approved (brainstorming)
**Version:** v1 (trontrace feature, builds on entity expansion)

## Problem Statement

The entity-expansion feature discovers a broad cohort of recurring recipients (hundreds), ranked
by a general confidence score in which **amount consistency carries only 10% weight**. As a
result the cohort over-includes one-off and variable-amount recipients, and the truly
*fixed-amount, regularly-paid* recipients are not surfaced as a distinct, high-precision group.

This feature makes **amount consistency the dominant signal** and adds a dedicated view that
ranks and filters recipients by their **fixed-amount recurring-payment profile**: a near-identical
amount paid across many months. It also flags likely **wallet-change pairs** — two addresses with
the same recurring amount in adjacent, non-overlapping month ranges (one stops, the other starts)
— for manual review, without auto-merging them.

### Goals
- Re-weight the core recipient score so a stable, repeated monthly amount dominates cohort
  membership and ranking.
- A dedicated, instantly-filterable list of fixed-amount recurring recipients (address, monthly
  amount, months, consistency), driven by configurable band / consistency / min-months.
- Flag probable wallet-change pairs (same amount, adjacent months) for manual review.

### Non-Goals (v1)
- Automatic merging of multiple addresses into one entity (deferred — see Roadmap).
- Identity attribution. Output is on-chain inference.

## Definitions

| Term | Meaning |
|------|---------|
| **Monthly series** | A recipient's per-UTC-month received totals (from `monthly_stats`). |
| **Amount consistency** | `1 − coefficient_of_variation(series)`, clamped to `[0,1]`. Identical monthly amounts → ~1.0. |
| **Fixed-amount recipient** | A recipient passing the band + consistency + min-months filters. |
| **Wallet-change hint** | A pair (A, B) with ~equal recurring amount whose active month ranges are adjacent and non-overlapping. |

## 1. Amount-Consistency Signal & Core Re-Weight

`app/analysis/expansion_signals.py` already computes `1 − CV` over a recipient's per-payment
amounts (currently `_amount_stability`). Promote it to a public `amount_consistency(values)` and
apply it as the **dominant** term of `recipient_score`. New default weights (sum 1.0):

| Signal | Old | New |
|--------|----:|----:|
| amount consistency | 0.10 | **0.40** |
| co-recipient | 0.35 | 0.25 |
| recurrence / tenure | 0.25 | 0.20 |
| pay-cycle alignment | 0.20 | 0.10 |
| low fan-in | 0.10 | 0.05 |

The existing `recurrence_min_months` hard gate (≥ 2 paid months) stays. Effect: a recipient paid a
near-identical amount across many months rises to High; variable-amount recipients fall. Weights
remain config constants (env-overridable) — these are new defaults.

**Known trade-off (intended):** recipients with deliberately variable amounts (bonuses, usage-based
pay) rank lower. This matches the feature's definition of a fixed-amount recurring profile.

## 2. Fixed-Amount Recipient View

New pure module `app/analysis/consistency.py` (no I/O, unit-tested):

- `ConsistentRow` — dataclass: `address`, `median_monthly` (int base units), `months_paid`,
  `consistency` (float).
- `consistent_rows(timelines, *, band_low, band_high, min_consistency, min_months) -> list[ConsistentRow]`
  — `timelines` maps address → list of `(year_month, amount_raw)`. For each address: compute the
  monthly series, its median, and `amount_consistency`; keep addresses where
  `consistency ≥ min_consistency`, `months_paid ≥ min_months`, and `band_low ≤ median ≤ band_high`;
  return sorted by `median_monthly` descending.

Config defaults (env-overridable): `consistent_band_low = 500_000000`,
`consistent_band_high = 12000_000000` (base units), `consistent_min_consistency = 0.80`,
`consistent_min_months = 4`.

## 3. Wallet-Change Hints

In `app/analysis/consistency.py` (pure):

- `wallet_change_hints(rows, timelines) -> list[tuple[str, str, str]]` — for each pair of rows
  (A, B), flag `(A, B, reason)` when **both**:
  1. `|median_A − median_B| / max(median_A, median_B) ≤ consistent_change_amount_tol` (default 0.10), and
  2. their active month ranges are non-overlapping and adjacent: A's last month precedes B's first,
     with a gap ≤ `consistent_change_max_gap_months` (default 1) — or vice-versa.

  Never pairs an address with itself. An address may appear in multiple hint pairs. Returns
  candidates for manual review only — no merging.

## 4. API, Frontend, Persistence

**API** — derived on read from `monthly_stats` (no new persistence; filters are instant, no re-run):
```
GET /api/consistent?band_low=&band_high=&min_consistency=&min_months=
→ { rows:  [{ address, amount, months, consistency }],
    hints: [{ a, b, reason }] }
```
Query params default to the config values. `amount` is formatted as a decimal string via the
existing `_fmt` helper. Reads cohort timelines (recipients present in `monthly_stats`), runs
`consistent_rows` then `wallet_change_hints`.

**Frontend** — new screen `/consistent` (route + nav link):
- Filter controls: band low/high, min consistency, min months.
- Table: address (click → `WalletDetail` + Tronscan) × amount/month × months × consistency.
- A "↔ possible same entity" badge on addresses that appear in a hint pair.
- CSV export of the current filtered rows.

**Reused as-is:** `monthly_stats` (written by expansion), `_fmt`, `WalletDetail`, the existing table
component patterns.

## 5. Edge Cases

| Case | Behavior |
|------|----------|
| 1 payment / 1 month | Excluded (min-months gate; consistency undefined for <2 points). |
| Identical amounts | consistency = 1.0; zero mean → 0. |
| Median outside band | Excluded (drops the large-business tail above `band_high` and dust below `band_low`). |
| Hint: overlapping months | Not flagged (must be non-overlapping + adjacent). |
| Hint: different amounts | Not flagged (must be within tolerance). |
| Address matches several | All candidate pairs returned for manual review. |
| Empty cohort | Empty `rows` and `hints`. |

## 6. Testing

- **Unit (`expansion_signals.py`):** `amount_consistency` (identical → ~1, variable → low, <2 points
  → 0); re-weight — a consistent-amount recipient now scores strictly higher than an otherwise-equal
  variable-amount one.
- **Unit (`consistency.py`):** `consistent_rows` filters by band / consistency / min-months and sorts
  by amount; `wallet_change_hints` flags an adjacent equal-amount pair and does NOT flag overlapping
  or different-amount pairs.
- **Integration:** `GET /api/consistent` against a seeded `monthly_stats` returns the expected rows
  and a hint, and respects query params.
- **Frontend:** `npm run build` passes (tsc + vite); no JS test runner.

## 7. Out of Scope / Roadmap
- **v1:** core re-weight, the consistent-recipient view + filters, wallet-change hints.
- **Later (v2):** automatic cross-address merging of one entity's wallets (the hints become an
  auto-merge step); per-recipient amount histograms in the detail panel.

## Config Parameters (new)

| Param | Default | Purpose |
|-------|---------|---------|
| `w_rec_stability` (+ rebalanced `w_rec_*`) | 0.40 (see §1) | amount consistency dominant in recipient score; all `w_rec_*` re-weighted per §1, sum 1.0 |
| `consistent_band_low` / `consistent_band_high` | 500e6 / 12000e6 | human amount band (base units) |
| `consistent_min_consistency` | 0.80 | min `1−CV` to count as fixed-amount |
| `consistent_min_months` | 4 | min paid months |
| `consistent_change_amount_tol` | 0.10 | amount tolerance for wallet-change hint |
| `consistent_change_max_gap_months` | 1 | max month gap between adjacent ranges |
