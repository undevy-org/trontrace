# Entity Expansion & Recurring-Recipient Discovery — Design Spec

**Date:** 2026-06-28
**Status:** Approved (brainstorming)
**Version:** v1 (trontrace feature)

## Problem Statement

The base trontrace pipeline starts from a single **anchor** wallet, finds the wallets that paid
it, clusters them into a **source entity** (the "primary payer"), and lists the entity's
recipients. That view is bounded by what touched the anchor directly: entity wallets that never
paid the anchor are invisible, so both the entity and its recipient list are partial.

This feature reconstructs the **full payer entity** behind the anchor's recurring inbound
payments — including wallets unknown to the base pipeline — and enumerates the entity's complete
cohort of **recurring recipients** (peers paid on the same cadence as the anchor), each with a
**confidence score** and a **payment timeline**. Single anchor input; no external seed.

### Goals
- Discover payer-entity wallets the base pipeline misses (no direct edge to the anchor).
- Enumerate all recurring recipients matching the entity's payment signature.
- Output a **confidence-ranked** list (nothing hard-dropped) with per-recipient payment
  timelines and tenure, including long-tenure recipients (12–24+ months).

### Non-Goals (v1)
- Linking recipients paid only via exchange withdrawals (no direct entity→recipient edge).
- Real-name attribution. Output is on-chain inference, not identity.

## Definitions

| Term | Meaning |
|------|---------|
| **Anchor** | The single input address. Seeded as a known recurring recipient (confidence 1.0). |
| **Entity wallet** | A payer wallet belonging to the source entity. |
| **Recurring recipient** | A payee with the entity's payment signature (recurring + low fan-in + per-payee stable amount). |
| **Pay-cycle fingerprint** | Day-of-month distribution of confirmed entity disbursements (the entity pays on fixed dates). |
| **Cohort** | The full set of recurring recipients of the entity. |

## Core Algorithm — Iterative Bipartite Expansion

A bipartite graph: entity wallets (payers) ↔ recurring recipients (payees). Grown by alternating
breadth-first expansion, seeded from the base pipeline.

**Seed.** Run the base pipeline → entity cluster `E₀` (wallets that paid the anchor). Seed
recipient set `C₀ = {anchor}` at confidence 1.0 (the one certain point under single-anchor).

**State.**
- `Payers`: {wallet → confidence}
- `Recipients`: {wallet → confidence, payment_timeline}
- Frontier queues of newly added nodes to expand.

**Round r:**
1. **Payee step.** For each new entity wallet, fetch its outbound (capped). Candidate recipients
   = payees with the recurring-payment signature. Score each (§Signals); add to `Recipients`
   (see §Signals).
   **Only High/Med recipients expand the frontier**; Low are recorded but not expanded
   (anti-drift).
2. **Payer step.** For each new recipient, fetch its inbound (capped). Candidate entity wallet =
   a sender that **co-pays ≥ K current recipients** AND aligns with the pay-cycle fingerprint AND
   passes the exchange gates (fan-in/fan-out). Score; add to `Payers`. This discovers
   **unknown entity wallets**.
3. Repeat until a round adds no High/Med node (**loop-until-dry**) or a budget cap is hit.

**Drift control.** The payer-step gate is the safeguard: a sender joins the entity only if
corroborated by **multiple** recipients on the pay-cycle dates and is not an exchange. A single
coincidental payment cannot promote a wallet. This conservatism is essential under single-anchor
(no ground-truth seed to validate against).

## Signals & Confidence

Two scores — recipient-side and payer-side — each in `[0, 1]`, bucketed into tiers
**High / Med / Low**. Only High/Med expand the frontier; all tiers appear in the ranked output.

### Pay-cycle fingerprint
Built from all confirmed `entity → recipient` payments: a histogram of UTC day-of-month. Fixed
pay dates produce peaks. A payment **aligns** if its day falls within ±`d` of a peak. Bootstrapped
from the anchor's own inbound stream; refined each round as the cohort grows.

### Recipient score (payee `p`)
- **co-recipient** — number of distinct entity wallets paying `p` (primary signal)
- **recurrence/tenure** — fraction of active months with a payment; strong bonus for 12–24+ months
- **pay-cycle alignment** — `p`'s inbound-from-entity payments land on pay dates
- **amount stability** — low per-payee variation (stable stream; not globally round)
- **low fan-in** — private wallet, not a hub

→ weighted sum → `conf_recipient(p)`

### Payer score (sender `w`)
- **co-recipient overlap** — overlap coefficient of `w`'s payees with the known cohort
- **pay-cycle alignment** — `w`'s outbound clusters on the pay dates
- **corroboration** — count of known recipients `w` pays (hard entry threshold ≥ `K`)
- **not an exchange** — passes fan-out (sender gate) and fan-in (not a hub)

→ weighted sum → `conf_payer(w)`

**Weights & thresholds** (`τ_high`, `τ_med`, `K`, `d`, signal weights) live in config as starting
heuristics. **co-recipient is the dominant signal** in both scores (empirically strongest);
pay-cycle is the secondary confirmer; the rest are supporting. Calibrate against a real run with
manual spot-check — synthetic tests prove the model is self-consistent, not that it matches
reality (per the project's validation philosophy).

## Architecture & Integration

New, heavier analysis mode layered on the existing infrastructure; the base pipeline is reused as
the seed and left unchanged.

**New modules (isolated, single-purpose):**
- `app/analysis/expansion_signals.py` — **pure** scoring: `pay_cycle_fingerprint`,
  `recipient_score`, `payer_score`, recurring-payment signature. No I/O; unit-testable like
  `similarity.py`.
- `app/expansion.py` — the BFS **engine** (alternating payee/payer steps, frontier, convergence).
  Depends on `trongrid` (fetch), `store` (persist), `expansion_signals`, `classify` (exchange gates).
  Single purpose: grow the bipartite graph.

**Reused as-is:** `trongrid` (pagination, caps, oversized-value drop), `classify.is_exchange*`
(gates), `monthly.aggregate_monthly` (payment timelines), the base pipeline (provides `E₀`).

**Data model (new table — confidence/tier/timeline richer than `wallets`):**
```sql
entity_nodes
  address              TEXT PRIMARY KEY,
  kind                 TEXT,      -- 'payer' | 'recipient'
  confidence           REAL,
  tier                 TEXT,      -- 'high' | 'med' | 'low'
  first_pay            INTEGER,   -- unix seconds, UTC
  last_pay             INTEGER,
  months_active        INTEGER,
  total_raw            INTEGER,   -- base units
  n_payers    INTEGER,   -- recipients only
  discovered_round     INTEGER
```
Per-recipient payment timeline reuses `monthly_stats` (address × month × amount). The pay-cycle
fingerprint is held in memory for the run.

**Entry point / API** (same pattern as the base pipeline; reuses `AnalysisManager`, progress):
- `POST /api/expand` — start expansion · `GET /api/status` — progress
- `GET /api/cohort` — ranked recipients: address, tier, amount/month, tenure, total, payers
- `GET /api/entity-wallets` — discovered entity wallets with confidence

**Frontend:** one new screen — a ranked recipient table reusing the existing table component and
the wallet-detail side panel. No dedicated graph view in v1 (YAGNI).

## Budget & Termination
- **loop-until-dry**: stop when a round adds no High/Med node.
- **Hard caps**: `max_rounds`, `max_payers`, `max_recipients`, `max_total_fetches` (API
  budget); per-wallet fetch caps reused from the base config.
- **Checkpoint**: reuse the `progress` row + `INSERT OR IGNORE` + `discovered_round`; an
  interrupted run resumes without re-fetching. Never lose fetched data.
- **Transparency**: per-round log (new recipients/employers, fetches spent). If a cap bounds the
  result, emit an explicit warning — no silent truncation.

## Error Handling
Reuse the base infrastructure: TronGrid retry/backoff on 429/5xx; pause + checkpoint on quota
exhaustion; idempotent writes. A run interrupted mid-expansion persists the partial graph and
resumes from the checkpoint.

## Edge Cases

| Case | Behavior |
|------|----------|
| Drift toward an exchange | Prevented by fan-in/fan-out gates + co-recipient ≥ `K`; a slipped hub is flagged exchange and not expanded. |
| Recipient paid only via exchange withdrawal (sender = CEX) | No direct entity→recipient edge; cannot be linked. Surfaced as an uncovered case. |
| Old / rotated-out entity wallets (tenure) | Discovered via recipients paid by both old and new wallets (time bridge). A wallet with no overlap to the current cohort is unreachable — noted. |
| Recipient who is also a one-off contractor | Scored; likely Med — user decides. |
| Anchor | Seeded as recipient at confidence 1.0; never re-added. |
| Convergence blow-up | Bounded by caps + the ≥ `K` corroboration gate; a hit cap is logged. |

## Testing
- **Unit** (`expansion_signals`): pay-cycle fingerprint from synthetic dates; recipient/payer scores
  on crafted inputs; tier boundaries.
- **Integration** (MockTransport): a synthetic bipartite scheme — several entity wallets (some
  that **never pay the anchor** = "unknown") co-paying a recipient set, plus decoys (an exchange
  hub, a one-off business payer, an unrelated sender). Assert: unknown entity wallets discovered,
  recipients found at correct tiers, decoys excluded, no drift.
- **Calibration**: a real run against the anchor with manual spot-check; record precision/recall;
  tune weights / `τ` / `K` / `d`.

## Config Parameters (new)

| Param | Purpose |
|-------|---------|
| `expand_tier_high` / `expand_tier_med` | confidence cutoffs for tiers / frontier expansion |
| `corecipient_min_k` (`K`) | min known recipients a sender must co-pay to join the entity |
| `paycycle_tolerance_days` (`d`) | ±days window around a pay-date peak |
| `expand_max_rounds` / `expand_max_payers` / `expand_max_recipients` | growth caps |
| `expand_max_total_fetches` | live-API budget for one run |
| signal weights (recipient, payer) | per-signal weights, co-recipient dominant |

## Out of Scope (v1) / Roadmap
- **v1:** the engine, signals, ranked output, one frontend screen.
- **Later:** dedicated cohort graph view; auto-merging multiple wallets of one recipient;
  cross-entity disambiguation when an anchor is paid by two distinct entities.
