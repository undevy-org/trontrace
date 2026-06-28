# Architecture

trontrace turns one **anchor wallet** into an entity-and-counterparty cash-flow map. This
document explains the moving parts and the attribution algorithm. Terminology is deliberately
generic — the same machinery serves any "who is this entity, and who do they pay" question, not
one specific scenario.

## Components

```
Browser (React) ──HTTP──> FastAPI backend
                              ├── SQLite (cache + results)
                              ├── Worker (async task, in-process, checkpointed)
                              └── TronGrid client (paginate, rate-limit, backoff)
```

- **Worker** runs the pipeline in the background, writing each fetched batch to SQLite *before*
  requesting the next page. One analysis at a time in v1.
- **Checkpoint**: the worker persists `phase`, `last_candidate`, and the last TronGrid
  `fingerprint`. On restart it resumes — already-fetched data is never re-requested.
  **Invariant: never lose already-fetched data.**

## Glossary

| Term | Meaning |
|------|---------|
| **Anchor wallet** | The single input address. Everything is discovered relative to it. |
| **Candidate** | A distinct address that sent the token to the anchor. |
| **Exchange wallet** | A custodial / high-fan-out address. Detected and excluded before clustering. |
| **Primary payer** | The cluster that pays the anchor the most in the recent window. |
| **Counterparty** | Any address the primary-payer cluster pays, other than the anchor. |

## Pipeline

```
Anchor wallet
   │
①  Inbound: who paid the anchor?        → candidates
②  Classify candidates                  → drop exchange / custodial wallets
③  Fetch candidate context (capped)     → outbound recipients R(W) + funding sources F(W)
④  Pairwise similarity + clustering     → wallet clusters
⑤  Select primary payer                 → by token paid to the anchor (NOT by cluster size)
⑥  Derive counterparties                → primary-payer recipients minus anchor/exchanges
⑦  Monthly totals per counterparty
```

## Why it is built this way

Two real-world facts drive every design decision:

1. **Payments often arrive via exchange withdrawals.** The on-chain sender is then a CEX hot
   wallet with millions of recipients. A naïve recipient-overlap metric would fuse half an
   exchange into one cluster and label strangers as counterparties. → We **gate out**
   high-fan-out / custodial wallets *before* clustering (`analysis/classify.py`).
2. **Unbounded fetch is intractable.** "Fetch all outbound for every sender" blows the data
   provider's rate/quota limits if any sender is high-volume. → Every per-wallet fetch is
   **capped**, and hitting the cap is itself a classification signal.

## Exchange / hot-wallet gate

A candidate is flagged `exchange` (excluded from clustering and counterparty derivation) if any:

1. **Static blocklist** — address is in `app/data/known_exchanges.json` (checked first, no
   network).
2. **Cap-hit** — outbound pagination exceeds `CANDIDATE_TX_CAP` before exhaustion.
3. **Fan-out** — distinct recipient count exceeds `FANOUT_CAP`.

This gate is the single most important correctness mechanism in the tool.

## Similarity (per pair of non-exchange candidates)

Three signals, each in `[0, 1]`:

**1 — Recipient overlap (weight 0.50).** Overlap coefficient, *not* Jaccard, because rotation
makes recipient sets highly asymmetric (a freshly rotated wallet has paid far fewer addresses):

```
overlap(A,B) = |R(A) ∩ R(B)| / min(|R(A)|, |R(B)|)        # 0 if either set empty
```

**2 — Payment rhythm (weight 0.30).** Closeness of cadence and amount:

```
med_int(W) = median gap (s) between consecutive outbound txs of W
med_amt(W) = median outbound amount of W
interval_sim = 1 − min(1, |med_int(A) − med_int(B)| / max(med_int(A), med_int(B)))
amount_sim   = 1 − min(1, |med_amt(A) − med_amt(B)| / max(med_amt(A), med_amt(B)))
rhythm_sim   = 0.5·interval_sim + 0.5·amount_sim
```

**3 — Shared funding (weight 0.20, positive-only bonus).** Overlap coefficient of funding
sources `F(W)` (who tops up the wallet), after removing exchange-flagged sources. Funding is a
*bonus*: its presence raises confidence, but its **absence never penalizes** — an entity may
fund rotated wallets from different sources, so missing funding overlap is weak evidence, not
counter-evidence.

```
base       = (0.50·overlap + 0.30·rhythm_sim) / (0.50 + 0.30)   # renormalized to [0,1]
score(A,B) = min(1, base + 0.20·funding_sim)
```

Weights and the threshold `τ = 0.55` are config constants — heuristics calibrated against a
real validation wallet (funding-as-bonus + τ=0.55 correctly merged 3 rotated payer wallets that
the naive 0.60 cutoff narrowly missed). Still tune per scheme.

## Clustering — average-linkage, not connected components

Single-linkage / connected-components chains unrelated wallets together (`A~B`, `B~C`, but
`A≁C` still merges all three). trontrace uses **agglomerative average-linkage**:

1. Seed each candidate as its own cluster.
2. Repeatedly merge the two clusters with the highest *average* pairwise score, while that
   average `> τ`.
3. Stop when no inter-cluster average exceeds `τ`.

Deterministic given fixed input; bounds intra-cluster cohesion; resists weak-chain blow-ups.

## Selecting the primary payer

Among clusters, the primary payer maximizes **total token paid to the anchor within
`PAYER_WINDOW_DAYS`** — *not* member count. (A missed exchange would form a large cluster but
is not the one paying the anchor.) All other candidates are labeled `noise`.

**Cluster confidence** = `avg_pairwise_score × signal_breadth`, where `signal_breadth` is the
fraction of the three signals that are non-zero on average within the cluster. A cluster
corroborated by all three signals outranks one resting on recipient overlap alone.

## Counterparties & monthly stats

- Counterparties = distinct recipients of the primary-payer cluster, minus the anchor, minus
  exchange-flagged recipients (surfaced separately as "needs manual check").
- Monthly totals are summed as **integer base units** (raw token decimals), grouped by UTC
  `YYYY-MM`. Conversion to a decimal string happens only at the display/CSV boundary —
  **no floating-point accumulation.**

## Data hygiene

Real token history contains **spam/spoof transfers** carrying absurd values (e.g. `2**256-1`).
Base units are stored as signed 64-bit ints; any value exceeding that ceiling (≈9.2×10¹⁸ — far
above real supply) is dropped at ingestion and counted in `FetchResult.skipped_oversized`.
A self-transfer by a payer wallet is never counted as its own counterparty.

## Validation

Synthetic unit tests prove the implementation matches the *model*, not that the model matches
reality. Accuracy is a **target**, confirmed per run by manual cross-check against a block
explorer (record precision/recall on ≥5 sampled wallets).

## Module map

| File | Responsibility |
|------|----------------|
| `app/config.py` | Settings, caps, weights, RPS (env-overridable) |
| `app/db.py` | SQLite schema + connection |
| `app/trongrid.py` | Paginated, rate-limited TronGrid client |
| `app/worker.py` | Pipeline orchestration + checkpoint |
| `app/analysis/classify.py` | Exchange / hot-wallet gate |
| `app/analysis/similarity.py` | overlap / rhythm / funding signals |
| `app/analysis/cluster.py` | Average-linkage clustering + primary-payer selection |
| `app/analysis/counterparties.py` | Counterparty derivation |
| `app/analysis/monthly.py` | UTC monthly aggregation (integer sums) |
| `app/api.py` | REST routes |
