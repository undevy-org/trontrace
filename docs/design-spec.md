# TRON Wallet Analyzer — Design Spec

**Date:** 2026-06-28
**Status:** Approved (brainstorming) · rewritten v2
**Version:** v1 MVP

---

## Problem Statement

The user receives USDT (TRC-20) payments on their TRON wallet from multiple sender
addresses. These senders belong to a single employer/counterparty who **rotates wallets**
over time. The same employer also pays many other recipients on a recurring schedule.

The user wants a **local** tool that, from their wallet address alone:

1. Identifies which wallets belong to the employer despite rotation.
2. Identifies the other recipients (counterparties) paid by the same employer.
3. Shows monthly statistics: how much each counterparty receives per calendar month.

**Single anchor input:** the user's wallet address only. No manual labeling in v1.

### What this tool is — and is not

The output is a **probabilistic inference from public on-chain data**, not a verified fact.
Wallet attribution is heuristic (target ~80–90% precision on clean private-wallet schemes,
materially lower when exchanges are involved). Every figure shown to the user is an estimate
that should be cross-checked on Tronscan before being treated as ground truth. The UI states
this explicitly (see §6 Overview).

---

## 1. Requirements Summary

| Parameter           | Decision                                            |
|---------------------|-----------------------------------------------------|
| Token               | USDT (TRC-20) only — contract `TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t` |
| Entry point         | User's wallet address only                          |
| Clustering          | Fully automatic                                     |
| History scope       | Full available history (bounded by per-wallet caps) |
| UI                  | Web (tables + graph + monthly filters)              |
| Deployment          | Local only (`localhost`)                            |
| Manual corrections  | Deferred to v1.1+                                    |

---

## 2. Core Analytical Model

### 2.1 Pipeline

```
User wallet
    │
 ①  Inbound: who paid me?              → raw sender candidates
    │
 ②  Classify candidates                → drop exchange / custodial hot wallets
    │
 ③  Fetch candidate context (capped)   → outbound recipients + funding sources
    │
 ④  Pairwise similarity + clustering   → wallet clusters
    │
 ⑤  Select Employer cluster            → by USDT paid to the user (not by size)
    │
 ⑥  Derive counterparties              → employer-cluster recipients minus user/exchanges
    │
 ⑦  Monthly totals per counterparty
```

### 2.2 Why the naïve version fails (design constraints)

Two real-world facts drive every decision below:

- **Salaries are often paid via exchange withdrawals.** The on-chain sender is then a CEX
  hot wallet (Binance/OKX/…) with **millions** of recipients. A naïve recipient-overlap
  metric would fuse half an exchange into one "employer" cluster and label random strangers
  as counterparties. → We must detect and exclude high-fan-out / custodial wallets **before**
  clustering (§3).
- **Unbounded fetch is intractable.** "Fetch all outbound for every sender" hits TronGrid
  rate/quota limits if any sender is high-volume. → Every per-wallet fetch is **capped**, and
  hitting the cap is itself a classification signal (§3, §7).

### 2.3 Definitions

- **Candidate** — a distinct `from_address` that sent USDT to the user.
- **Recipient set** `R(W)` — distinct addresses W paid in USDT, **excluding** the user and
  excluding any address flagged as an exchange/custodial wallet.
- **Funding set** `F(W)` — distinct addresses that sent USDT **to** W (W's top-up sources),
  capped (§7).
- **Employer cluster** — the cluster maximizing total USDT paid to the user in the recent
  window (§4.3).
- **Counterparty** — any address in `⋃ R(W)` over employer-cluster wallets W, excluding the
  user. Exchange-flagged recipients are surfaced separately, not as ordinary counterparties.

---

## 3. Exchange / Hot-Wallet Detection (gate before clustering)

A candidate is classified as **EXCHANGE** (custodial / high-fan-out, excluded from clustering
and from counterparty derivation) if **any** of:

1. **Static blocklist hit** — address is in the bundled list of known TRON hot wallets
   (`data/known_exchanges.json`, ships with the repo, manually curated; covers major CEXs and
   common payment processors). Checked first — cheap, no network.
2. **Cap-hit during fetch** — while paginating the candidate's outbound transfers we exceed
   `CANDIDATE_TX_CAP` (default **5,000** tx) and pagination is not exhausted → treat as
   high-volume, stop fetching, flag EXCHANGE.
3. **Fan-out threshold** — distinct outbound recipient count `|R_raw(W)| > FANOUT_CAP`
   (default **2,000**). A genuine private employer wallet rarely pays thousands of distinct
   addresses; an exchange does.

EXCHANGE-flagged candidates are kept in the DB with `role = 'exchange'`, shown in the Overview
"Excluded" section, and never contribute to cluster scores or counterparty totals. This gate is
the single most important correctness mechanism in the tool.

> All three thresholds are config constants (`config.py` / `.env` overridable) so they can be
> tuned without code changes.

---

## 4. Clustering

### 4.1 Pairwise similarity

For every pair of **non-exchange** candidates (A, B), compute three signals, each in `[0, 1]`:

**Signal 1 — Recipient overlap (weight 0.50).** Use the **overlap coefficient**, not Jaccard,
because rotation makes recipient sets highly asymmetric (a freshly rotated wallet has paid far
fewer addresses than the old one):

```
overlap(A, B) = |R(A) ∩ R(B)| / min(|R(A)|, |R(B)|)        # 0 if either set empty
```

**Signal 2 — Payment rhythm (weight 0.30).** Defined concretely over each wallet's outbound
USDT stream:

```
intervals(W)   = sorted gaps (seconds) between consecutive outbound USDT txs of W
med_int(W)     = median(intervals(W))
med_amt(W)     = median(outbound USDT amounts of W)

interval_sim(A,B) = 1 − min(1, |med_int(A) − med_int(B)| / max(med_int(A), med_int(B)))
amount_sim(A,B)   = 1 − min(1, |med_amt(A) − med_amt(B)| / max(med_amt(A), med_amt(B)))

rhythm_sim(A,B)   = 0.5 × interval_sim + 0.5 × amount_sim
```

Wallets with fewer than 2 outbound txs (no interval) get `interval_sim = 0`.

**Signal 3 — Shared funding (weight 0.20).** Requires candidate **inbound** data (collected in
Phase 2b, §8). Overlap coefficient of funding sources, after removing exchange-flagged sources:

```
funding_sim(A, B) = |F(A) ∩ F(B)| / min(|F(A)|, |F(B)|)    # 0 if either set empty
```

**Combined score:**

```
score(A, B) = 0.50 × overlap(A, B)
            + 0.30 × rhythm_sim(A, B)
            + 0.20 × funding_sim(A, B)
```

Weights and the cluster threshold `τ = 0.60` are config constants. They are **starting
heuristics, not calibrated values** — see §13 Validation.

### 4.2 Forming clusters (average-linkage, not transitive closure)

A single-linkage / connected-components approach chains unrelated wallets together
(`A~B`, `B~C`, but `A≁C` still merges all three). We instead use **agglomerative
average-linkage** clustering with threshold `τ`:

1. Seed each candidate as its own cluster.
2. Repeatedly merge the two clusters with the highest **average** pairwise score across their
   members, while that average `> τ`.
3. Stop when no inter-cluster average exceeds `τ`.

This bounds intra-cluster cohesion (every member is on average similar to the rest) and
prevents weak-chain blow-ups. Deterministic given fixed input.

### 4.3 Selecting the Employer cluster

Among the resulting clusters, the **Employer** is the cluster maximizing **total USDT paid to
the user within the recent window** (`EMPLOYER_WINDOW`, default last **6 months**) — *not* the
largest cluster by member count. Rationale: a missed exchange that slipped the gate would form
a big cluster, but it is not the one paying you a salary.

All other candidate senders are labeled **Noise** (`role = 'noise'`) and excluded from
counterparty statistics.

### 4.4 Cluster confidence

```
confidence(C) = avg_pairwise_score(C) × signal_breadth(C)
signal_breadth(C) = fraction of the 3 signals that are non-zero on average within C
```

A cluster supported by all three signals scores higher than one resting on recipient overlap
alone. Surfaced as a percentage in the UI; clamped to `[0, 1]`.

---

## 5. Counterparties & Monthly Statistics

### 5.1 Counterparty derivation

Counterparties = distinct recipients across all Employer-cluster wallets, **excluding** the
user and excluding exchange-flagged recipients. Exchange-flagged recipients are listed in a
separate "Needs manual check" group with a Tronscan link rather than counted as income.

> **Known limitation (stated in UI):** counterparty discovery is anchored on wallets that paid
> *the user*. Employer wallets that pay others but never paid the user are invisible to this
> method, so the counterparty list is necessarily **partial**.

### 5.2 Monthly statistics

- Group by calendar month in **UTC** (`YYYY-MM`).
- Amounts are summed as **integer micro-USDT** (raw 6-decimal units); converted to decimal only
  at the display/CSV boundary. No floating-point accumulation.
- Table: rows = counterparties (+ a separate "You" row), columns = months, cells = USDT total.
- A month with no payment renders as empty/0, not omitted.
- v1 does **not** merge multiple wallets belonging to the same counterparty (each address = its
  own row).

---

## 6. UI Screens

### Screen 1 — Start / Analysis
- Input: TRON address (`T...`) with client- and server-side validation.
- Button: "Start analysis".
- Progress indicator: phase name + percentage (polled via `/api/status`).
- One active analysis at a time in v1.

### Screen 2 — Overview
- Employer cluster: grouped wallets with confidence %.
- User payments: total and monthly average.
- Counterparty count.
- **Excluded (likely exchange):** collapsed section listing gated hot wallets.
- **Noise:** collapsed section for non-cluster senders.
- **Disclaimer banner:** "Results are heuristic estimates from public on-chain data, not
  verified facts. Cross-check on Tronscan." Shown if cluster confidence < 0.7 or history
  < 3 months.

### Screen 3 — Monthly Table (primary screen)
- Rows: counterparties + "You".
- Columns: calendar months (UTC).
- Filters: date range, address search, sort by total.
- Export: CSV download.

### Screen 4 — Connection Graph
- Interactive Cytoscape.js graph.
- Node colors: green = employer cluster · blue = user · yellow = counterparties ·
  gray = noise · red = excluded exchange.
- Edge thickness proportional to USDT volume.
- Month filter rebuilds the graph for the selected period.

### Screen 5 — Wallet Detail (side panel)
- Full address with copy.
- Role: Employer / Counterparty / Noise / Exchange.
- Confidence %.
- First/last activity.
- Top 5 senders / recipients.
- Link to Tronscan.

### Navigation
```
[Overview]  [Monthly Table]  [Graph]            Address: TYour...wallet
```

---

## 7. Technical Architecture

### 7.1 Stack

| Layer            | Technology                                            |
|------------------|-------------------------------------------------------|
| Frontend         | React + Vite, TanStack Table, Cytoscape.js            |
| Backend          | Python + FastAPI                                       |
| Background work  | `asyncio` task + persistent SQLite checkpoint (§8.3)  |
| Database         | SQLite (`data/analyzer.db`)                            |
| Blockchain data  | TronGrid API (USDT TRC-20)                             |

### 7.2 Components

```
Browser (React) ←HTTP→ FastAPI Backend
                           ├── SQLite (cache + results)
                           ├── Worker (async task, in-process, checkpointed)
                           └── TronGrid API client (paginate, rate-limit, backoff)
```

- **Worker:** paginates TronGrid (200 tx/request via `fingerprint`), writes each batch to
  SQLite **before** requesting the next page, and honors `CANDIDATE_TX_CAP` / `FANOUT_CAP`.
- **TronGrid client:** filters by USDT `contract_address`; respects rate limits with exponential
  backoff on 429; caps total in-flight concurrency to stay under quota.
- **TronGrid API key:** stored in `.env`, server-side only, never sent to the frontend.

### 7.3 Caps & constants (config)

| Constant            | Default   | Purpose                                            |
|---------------------|-----------|----------------------------------------------------|
| `CANDIDATE_TX_CAP`  | 5,000     | Max tx fetched per candidate before exchange-flag  |
| `FANOUT_CAP`        | 2,000     | Distinct-recipient ceiling for non-exchange        |
| `FUNDING_FETCH_CAP` | 1,000     | Max inbound tx fetched per candidate (Signal 3)    |
| `SCORE_THRESHOLD τ` | 0.60      | Average-linkage merge threshold                    |
| `EMPLOYER_WINDOW`   | 6 months  | Recent window for Employer selection               |
| Signal weights      | .50/.30/.20 | overlap / rhythm / funding                        |

---

## 8. Data Flow

### 8.1 Phase 1 — Inbound (user)
Fetch all USDT transfers **to** the user → extract distinct sender addresses (candidates) →
save txs + candidate wallets to SQLite.

### 8.2 Phase 2 — Candidate context (capped). *Longest phase.*
For each candidate, in order:
- **2a · Static gate:** if in `known_exchanges.json` → mark `exchange`, skip fetch.
- **2b · Outbound fetch (capped):** paginate outbound USDT, writing each batch immediately.
  If `CANDIDATE_TX_CAP` exceeded before exhaustion, or `|R_raw| > FANOUT_CAP` → mark `exchange`,
  stop.
- **2c · Inbound fetch (capped at `FUNDING_FETCH_CAP`):** collect funding sources `F(W)` for
  Signal 3.

### 8.3 Phase 3 — Clustering
Compute pairwise scores among non-exchange candidates → average-linkage clustering → select
Employer cluster by USDT-to-user in `EMPLOYER_WINDOW` → write `clusters` + `wallets.role`.

### 8.4 Phase 4 — Aggregation
Derive counterparties (§5.1) → compute `monthly_stats` grouped by counterparty and UTC month,
in integer micro-USDT.

### 8.5 Checkpointing
The worker records the current phase, the last completed candidate, and the last TronGrid
`fingerprint` in a `progress` row. On restart it resumes from the checkpoint — already-fetched
batches are never re-requested. **Invariant: never lose already-fetched data.**

---

## 9. Database Schema

All amounts are **integer micro-USDT** (`INTEGER`, raw 6-decimal units). No floats anywhere.

```sql
wallets
  address      TEXT PRIMARY KEY,
  first_seen   INTEGER,            -- unix seconds, UTC
  last_seen    INTEGER,
  role         TEXT,               -- 'user' | 'employer' | 'counterparty' | 'noise' | 'exchange'
  cluster_id   INTEGER             -- nullable; FK → clusters.cluster_id

transactions
  tx_hash      TEXT PRIMARY KEY,
  from_address TEXT NOT NULL,
  to_address   TEXT NOT NULL,
  amount_raw   INTEGER NOT NULL,   -- micro-USDT
  timestamp    INTEGER NOT NULL,   -- unix seconds, UTC
  token        TEXT NOT NULL       -- 'USDT' (forward-compat)

clusters
  cluster_id   INTEGER PRIMARY KEY,
  label        TEXT,               -- 'Employer' | 'Noise' | ...
  confidence   REAL,               -- [0,1]
  created_at   INTEGER

monthly_stats
  counterparty_address TEXT NOT NULL,
  year_month           TEXT NOT NULL,   -- 'YYYY-MM' (UTC)
  total_raw            INTEGER NOT NULL,
  tx_count             INTEGER NOT NULL,
  PRIMARY KEY (counterparty_address, year_month)

progress
  id           INTEGER PRIMARY KEY CHECK (id = 1),  -- single-row
  phase        TEXT,
  last_candidate TEXT,
  last_fingerprint TEXT,
  percent      INTEGER,
  updated_at   INTEGER

-- Indexes (queried constantly on 100k+ tx)
CREATE INDEX idx_tx_from  ON transactions(from_address);
CREATE INDEX idx_tx_to    ON transactions(to_address);
CREATE INDEX idx_tx_time  ON transactions(timestamp);
CREATE INDEX idx_wallet_cluster ON wallets(cluster_id);
```

---

## 10. REST API

| Method | Path                       | Description                                   |
|--------|----------------------------|-----------------------------------------------|
| POST   | `/api/analyze`             | Start analysis `{ "address": "T..." }`        |
| GET    | `/api/status`              | Progress `{ "phase", "percent" }`             |
| GET    | `/api/overview`            | Summary: cluster, totals, counts, exclusions  |
| GET    | `/api/monthly?from=&to=`   | Monthly table data                            |
| GET    | `/api/graph?month=`        | Graph nodes/edges for Cytoscape               |
| GET    | `/api/wallet/{address}`    | Single wallet details                         |
| GET    | `/api/export/csv`          | CSV download                                  |

`POST /api/analyze` returns `409 Conflict` if an analysis is already running (one at a time in
v1). All amounts in responses are decimal USDT strings (converted from `amount_raw`) to avoid
JSON float precision loss.

---

## 11. Local Run

```bash
# 1. Set TRONGRID_API_KEY in .env  (see README)
# 2. Either:
docker compose up
#    or:
./start.sh            # backend :8000, frontend :3000
```

Missing API key blocks startup with explicit `.env` instructions.

---

## 12. Error Handling

| Situation                          | Behavior                                                   |
|------------------------------------|-----------------------------------------------------------|
| Invalid address                    | Immediate validation error on start screen                |
| TronGrid 429 / rate-limited        | Exponential backoff, retry up to 3×; then user-facing error |
| TronGrid 5xx / unavailable         | Same retry policy; surface clear error                    |
| Daily quota exhausted              | Pause, persist checkpoint, instruct user to resume later  |
| No inbound USDT                    | Informational empty result                                |
| Candidate exceeds caps             | Auto-flag `exchange`, continue (not an error)             |
| Analysis interrupted               | Resume from SQLite checkpoint on next run                 |
| Very large dataset (>100k tx)      | Warning before proceeding                                 |
| Missing API key                    | Block startup with clear `.env` instructions              |

**Principle:** never lose already-fetched data — each batch is written to SQLite before the
next request.

---

## 13. Validation & Accuracy

The synthetic unit tests verify that the implementation matches the *model*; they cannot prove
the model matches reality. Accuracy is therefore claimed only as a **target**, confirmed per
run by manual cross-check:

- **Synthetic graphs** (unit): clustering produces the known expected clusters; covers rotation
  asymmetry (overlap coefficient), chaining resistance (average-linkage), and exchange gating.
- **Manual ground-truth** (per real run): pick ≥5 attributed wallets, verify on Tronscan; record
  precision/recall in the run report. Accuracy figures in the README cite this method, not a
  bare "80–90%".

---

## 14. Privacy & Security

- All results stored locally (SQLite, `.env`). No third-party analytics.
- API key server-side only; never reaches the frontend.
- `.env` and `data/` in `.gitignore`.
- **Disclosure (README + UI):** "Local" means stored locally, **not** private from the data
  provider — TronGrid sees every address queried during analysis.

---

## 15. Testing Strategy

| Level       | Scope                                                                 |
|-------------|-----------------------------------------------------------------------|
| Unit        | Clustering on synthetic graphs (rotation, chaining, exchange gate)    |
| Unit        | Overlap coefficient, rhythm_sim, funding_sim formulas (edge inputs)   |
| Unit        | Monthly aggregation (UTC boundaries, empty months, integer sums)      |
| Integration | Mock TronGrid → full pipeline to `monthly_stats`, incl. cap-hit paths |
| Manual      | Real wallet cross-checked against Tronscan (§13)                      |

No live TronGrid calls in CI (rate limits). Mock fixtures include a high-fan-out wallet to
exercise the exchange gate.

---

## 16. Edge Cases

| Case                                          | v1 Behavior                                              |
|-----------------------------------------------|---------------------------------------------------------|
| Salary paid via exchange withdrawal           | Sender flagged `exchange`, excluded; surfaced in Overview |
| Non-employer senders (refunds, friends)       | Classified as Noise                                     |
| Employer changed scheme years ago             | May yield multiple clusters; recent USDT-to-user = Employer |
| Counterparty with multiple wallets            | Each address = separate table row                       |
| Multiple employer wallets pay user same day   | Summed into single "You" monthly cell                   |
| < 3 months of history                         | Low-confidence disclaimer banner on Overview            |
| Exchange/mixer as recipient                   | "Needs manual check" group, Tronscan link, not counted  |
| Candidate with > cap transactions             | Flagged `exchange` on cap-hit                            |
| Employer wallet that never paid the user      | Not discoverable; counterparty list is partial (stated) |

---

## 17. v1 Definition of Done

- [ ] Address input and analysis with progress UI
- [ ] Full USDT history fetch via TronGrid with SQLite cache and per-candidate caps
- [ ] Exchange/hot-wallet gate (static list + cap-hit + fan-out)
- [ ] Auto-cluster senders into Employer / Noise via average-linkage on the 3-signal score
- [ ] Counterparty list (employer-cluster recipients minus user/exchanges)
- [ ] Monthly table: counterparty × month × USDT (integer-summed) with filters
- [ ] "You" row in monthly table
- [ ] Interactive connection graph with month filter and exchange/noise coloring
- [ ] CSV export
- [ ] Resume-from-checkpoint after interruption
- [ ] Single-command local startup
- [ ] README: setup, API key, run instructions, accuracy method, privacy disclosure

---

## 18. Out of Scope (v1)

- Manual label corrections
- Multiple user-wallet entry points
- Counterparty wallet merging
- TRX or other tokens
- Cloud deployment
- Auto-maintained exchange-label database (v1 ships a static list only)

---

## 19. Roadmap

| Version | Features                                                                 |
|---------|--------------------------------------------------------------------------|
| v1.1    | Manual corrections: exclude wallet, merge clusters, override exchange flag |
| v1.2    | Multiple user wallets as entry points                                    |
| v2      | Auto-merge counterparty wallets; live exchange-label feed; new-tx notifications; weight calibration from labeled data |

---

## 20. v1 Limitations (explicit)

- USDT TRC-20 only.
- First analysis may take 15–40 minutes for active schemes (bounded by per-candidate caps; a
  scheme dominated by exchange senders resolves faster because those wallets are gated, not
  deep-fetched).
- Clustering is heuristic (target ~80–90% precision on clean private-wallet schemes, lower with
  exchange involvement; not forensic-grade). Every figure is an estimate.
- Single user-wallet entry point → counterparty list is partial (employer wallets that never
  paid the user are invisible).
- Calendar months in UTC.
- No manual override in v1.
- Heuristic thresholds (weights, τ, caps) are uncalibrated defaults, tunable via config.
```

