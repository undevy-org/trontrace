# Contributing

Thanks for your interest in trontrace.

## Development setup

```bash
# Backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pytest

# Frontend
cd frontend
npm install
npm run dev
```

## Project layout

- `backend/app/analysis/` — pure, I/O-free analysis logic (similarity, clustering, exchange
  gate, monthly aggregation). Fully unit-tested; keep it pure.
- `backend/app/` — config, SQLite, TronGrid client, worker, REST API.
- `frontend/src/` — React + Vite UI.
- `docs/` — design spec. `ARCHITECTURE.md` — algorithm overview. `CHANGELOG.md` — release notes.

## Conventions

- **Amounts are integer base units** (raw token decimals) everywhere internally. Convert to a
  decimal string only at the display/CSV boundary. Never accumulate in floating point.
- **Time is UTC.** Monthly buckets are `YYYY-MM` in UTC.
- Analysis logic in `analysis/` stays free of network/database calls so it can be unit-tested.
- All thresholds and weights live in `app/config.py` and are environment-overridable.

## Tests

Add unit tests for any change to the analysis core. No live TronGrid calls in tests — use
recorded or mock responses. Run `pytest` from `backend/` before opening a PR.

## Pull requests

Keep PRs focused. Note user-facing changes in `CHANGELOG.md`.
