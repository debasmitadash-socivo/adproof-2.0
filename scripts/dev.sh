#!/usr/bin/env bash
# Boot both servers in dev mode. Run from project root.
#   ./scripts/dev.sh
set -e

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# Ensure Python 3.11+ venv exists with backend + analytics deps.
if [ ! -d "$ROOT/.venv" ]; then
  echo "Creating Python venv (needs python3.12 or newer)…"
  python3.12 -m venv "$ROOT/.venv"
  "$ROOT/.venv/bin/pip" install --upgrade pip
  "$ROOT/.venv/bin/pip" install -r "$ROOT/requirements.txt"
  "$ROOT/.venv/bin/pip" install -r "$ROOT/api/requirements.txt"
fi

# Ensure web/ deps are installed.
if [ ! -d "$ROOT/web/node_modules" ]; then
  echo "Installing web dependencies…"
  (cd "$ROOT/web" && npm install)
fi

echo
echo "Starting API on http://localhost:8000  &  Web on http://localhost:3000"
echo "Open http://localhost:3000 — Ctrl-C in this terminal stops both."
echo

# Start API in background, web in foreground; trap kills the api on exit.
(
  cd "$ROOT/api" && "$ROOT/.venv/bin/uvicorn" main:app --reload --port 8000
) &
API_PID=$!
trap 'kill $API_PID 2>/dev/null || true' EXIT

(cd "$ROOT/web" && npm run dev)
