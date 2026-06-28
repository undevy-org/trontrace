# trontrace

**Trace TRC-20 token cash flows from a single anchor wallet.**

Give trontrace one TRON address. It walks the public on-chain history, figures out which
wallets behave as **one entity** (despite wallet rotation), discovers the **counterparties**
that entity pays, and shows **monthly totals** per counterparty — as a table and an interactive
graph.

It runs entirely on your machine. Nothing is uploaded anywhere except read-only queries to the
blockchain data provider.

> ⚠️ **Results are heuristic estimates from public on-chain data, not verified facts.**
> Wallet attribution is probabilistic. Always cross-check on a block explorer before treating
> any figure as ground truth. See [Limitations](#limitations).

---

## What it does

Starting from one **anchor wallet**, trontrace runs a fixed pipeline:

1. **Inbound** — who paid the anchor? → *source candidates*
2. **Classify** — drop exchange / custodial hot wallets (they would poison the analysis)
3. **Context** — for each candidate, fetch its outbound recipients and funding sources (capped)
4. **Cluster** — group candidates that behave as one entity (recipient overlap + payment rhythm
   + shared funding)
5. **Select primary payer** — the cluster that pays the anchor the most in the recent window
6. **Counterparties** — everyone else the primary-payer cluster pays
7. **Monthly totals** — per counterparty, per calendar month (UTC)

The clustering and aggregation are **token- and purpose-agnostic**. The default configuration
targets USDT (TRC-20), but the same machinery works for any TRC-20 token and any "who is this
entity and who do they pay" question. Common uses: tracing a recurring payer across rotated
wallets, mapping a payroll/affiliate payout graph, or auditing your own counterparties.

## How it works (algorithm)

The attribution logic — similarity signals, the exchange gate, average-linkage clustering, and
why it is built this way — is documented in **[ARCHITECTURE.md](ARCHITECTURE.md)**. The full
design spec lives in [`docs/design-spec.md`](docs/design-spec.md).

## Stack

| Layer            | Technology                                  |
|------------------|---------------------------------------------|
| Frontend         | React + Vite · TanStack Table · Cytoscape.js |
| Backend          | Python + FastAPI                             |
| Background work  | in-process `asyncio` task, SQLite checkpoint |
| Database         | SQLite (local file)                          |
| Blockchain data  | [TronGrid](https://www.trongrid.io/) API     |

## Quick start

```bash
git clone https://github.com/undevy-org/trontrace.git
cd trontrace
cp .env.example .env          # then edit .env and paste your TronGrid API key

# Option A — Docker
docker compose up

# Option B — local processes
./start.sh                    # backend :8000, frontend :3000
```

Open <http://localhost:3000>, paste an anchor address (`T...`), and start the analysis.

### Getting a TronGrid API key

1. Create a key at <https://www.trongrid.io/> → **API Keys**.
2. Paste it into `.env` as `TRONGRID_API_KEY`. **Never commit `.env`** — it is gitignored.
3. Free keys are limited to **15 requests/second**; trontrace stays below this by default
   (`TRONGRID_MAX_RPS=12`).

**Key security (optional hardening).** trontrace uses the key server-side only, so the
provider's AllowList settings (Origins, User-Agent, JWT) are not required. The one worthwhile
optional restriction is **AllowList Contract Addresses → the USDT contract**, which limits the
blast radius if the key ever leaks. Leave it off if it interferes with account endpoints.

## Privacy

- All results stay in a local SQLite file. No third-party analytics.
- The API key is read server-side only and never reaches the browser.
- "Local" means *stored* locally — it does **not** mean private from the data provider.
  TronGrid sees every address queried during an analysis.

## Limitations

- Default token is USDT (TRC-20); other TRC-20 tokens work via `TOKEN_CONTRACT`.
- Attribution is heuristic (target ~80–90% precision on clean private-wallet schemes, lower when
  exchanges are involved; **not** forensic-grade).
- Discovery is anchored on wallets that paid *the anchor*. Entity wallets that pay others but
  never paid the anchor are invisible → the counterparty list is **partial**.
- Calendar months are bucketed in **UTC**.
- The first analysis of an active scheme can take 15–40 minutes (bounded by per-wallet caps).
- Thresholds (signal weights, score cutoff, caps) are uncalibrated defaults, tunable via config.

## Development

```bash
# Backend
cd backend && pip install -r requirements.txt && pytest

# Frontend
cd frontend && npm install && npm run dev
```

## License

[MIT](LICENSE) © undevy-org
