#!/usr/bin/env bash
# Start backend (:8000) and frontend (:3000) as local processes.
# For containers use `docker compose up` instead.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ ! -f "$ROOT/.env" ]]; then
  echo "Missing .env — copy .env.example to .env and add your TRONGRID_API_KEY." >&2
  exit 1
fi

cleanup() { kill 0 2>/dev/null || true; }
trap cleanup EXIT INT TERM

echo "Starting backend on :8000 ..."
(
  cd "$ROOT/backend"
  python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
) &

echo "Starting frontend on :3000 ..."
(
  cd "$ROOT/frontend"
  npm run dev -- --port 3000
) &

wait
