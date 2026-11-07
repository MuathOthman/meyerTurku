#!/usr/bin/env bash
# Starts the backend on :8000 and the frontend on :5173. Open http://localhost:5173.
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -x backend/.venv/bin/uvicorn ]; then
  echo "Backend is not installed. Run: cd backend && python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'" >&2
  exit 1
fi
[ -d frontend/node_modules ] || npm --prefix frontend install

(cd backend && exec .venv/bin/uvicorn api.main:app --reload --reload-dir api --reload-dir keel --timeout-graceful-shutdown 3 --port 8000) &
backend=$!
trap 'kill "$backend" 2>/dev/null || true' EXIT

npm --prefix frontend run dev
