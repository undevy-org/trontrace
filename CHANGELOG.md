# Changelog

All notable changes to this project are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/); this project adheres to semantic versioning.

## [Unreleased]

### Added
- **Consistent-amount recipient ranking** (`app/analysis/consistency.py`): amount consistency is
  now the dominant recipient signal (re-weighted `recipient_score`), and a `/consistent` view +
  `GET /api/consistent` rank fixed-amount recurring recipients (address × amount/month × months ×
  consistency) with configurable band / consistency / min-months and CSV export. Flags likely
  **wallet-change pairs** (same recurring amount in adjacent, non-overlapping months) for manual
  review — no auto-merging. Validated on a real wallet: collapses a heuristic cohort of ~217 to
  ~25 fixed-amount recipients (the anchor itself self-validates at its known amount).
- **Entity expansion & recurring-recipient discovery** (`app/expansion.py`,
  `app/analysis/expansion_signals.py`): from a single anchor, an iterative bipartite BFS grows
  the payer entity beyond the wallets that paid the anchor — discovering previously-unknown
  entity wallets — and enumerates the full cohort of recurring recipients, confidence-ranked
  (High/Med/Low tiers). Signals: co-recipient overlap, pay-cycle fingerprint, tenure-based
  recurrence, amount stability, fan-in. New `entity_nodes` table; endpoints `/api/expand`,
  `/api/cohort`, `/api/entity-wallets`; a Cohort frontend screen. Spec/plan under
  `docs/superpowers/`.
  - Calibrated on a real wallet: the recurrence signal was corrected to reward absolute tenure
    (`recurrence_target_months`) with a minimum-months hard gate (`recurrence_min_months`) — a
    single payment is no longer treated as "recurring", which had flooded the cohort with
    one-off recipients.

- **Recipient-side fan-in gate** (`is_exchange_recipient`, opt-in via `recipient_gate`): a
  counterparty fed by many distinct senders (`recipient_fanin_cap`, default 50) is flagged as
  exchange/processor and dropped from the counterparty list. Motivated by real-data analysis —
  top "counterparties" by volume were exchange deposit hubs (150–700+ distinct senders), not
  genuine peers. Off by default (adds an inbound fetch per counterparty).

## [0.1.0] — 2026-06-28

First working release: trace TRC-20 token cash flows from a single anchor wallet.

### Added — analysis core
- **Pipeline** (`pipeline.py`): inbound fetch → candidate context → exchange gate → clustering →
  primary-payer selection → counterparty derivation → monthly aggregation.
- **Similarity** (`analysis/similarity.py`): recipient overlap (overlap coefficient, handles
  rotation asymmetry), payment rhythm, shared funding. Funding is a **positive-only bonus** —
  its absence never penalizes.
- **Clustering** (`analysis/cluster.py`): agglomerative average-linkage (resists weak-chain
  blow-ups); primary payer selected by **volume paid to the anchor**, not cluster size.
- **Exchange gate** (`analysis/classify.py`): static blocklist + cap-hit + fan-out, applied
  before clustering so custodial hot wallets cannot poison the result.
- **Monthly aggregation** (`analysis/monthly.py`): UTC `YYYY-MM` buckets, exact integer
  base-unit sums, decimal formatting only at the boundary (no floating-point accumulation).

### Added — infrastructure
- **TronGrid client** (`trongrid.py`): `fingerprint` pagination, token-bucket rate limiting,
  exponential backoff on 429/5xx, normalization (ms→s, value string→int).
- **SQLite store** (`store.py`, `db.py`): transactions/wallets/clusters/monthly_stats + indexes
  and a single-row progress checkpoint.
- **Worker** (`worker.py`): one analysis at a time, idempotent re-run resume.
- **REST API** (`api.py`, FastAPI): `/analyze`, `/status`, `/overview`, `/monthly`, `/graph`,
  `/wallet/{address}`, `/export/csv`. Amounts serialized as decimal strings.
- **Frontend** (React + Vite): Start (with live progress), Overview, Monthly Table (filters +
  CSV), Cytoscape connection graph (role colors, month filter), Wallet Detail side panel.
- Local run via `docker compose up` or `./start.sh`; secrets in gitignored `.env`.

### Validation
- Verified end-to-end against a real anchor wallet: correctly identified 3 rotated payer
  wallets and 363 counterparties (matched ground truth). Frontend exercised live against the
  backend across all five screens.

### Fixed (surfaced by the real-data run)
- **Spam/spoof transfer values** (e.g. `2**256-1`) no longer crash ingestion — values above the
  int64 storage ceiling are dropped and counted (`FetchResult.skipped_oversized`).
- **Primary-payer role overwrite**: a payer that self-transfers is no longer relabeled as its
  own counterparty.

### Changed
- Clustering recalibrated against the validation wallet: funding-as-bonus + threshold `τ = 0.55`
  (the naïve `0.60` cutoff narrowly missed three genuinely-related rotated wallets).
- Wallet Detail side panel sits below the (now sticky) navbar so navigation stays clickable
  while the panel is open.

### Known limitations
- Heuristic thresholds are tuned defaults — recalibrate per scheme (all in `config.py` / `.env`).
- Counterparty discovery is anchored on wallets that paid the anchor, so it is necessarily
  partial (see `ARCHITECTURE.md`).
- Verified via both `docker compose up` (full stack, real analysis through the containers) and
  the local-process path.
