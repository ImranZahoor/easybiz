#!/usr/bin/env bash
# Run the dev server, optionally alongside the event dispatcher.
#
# Usage: ./scripts/run.sh [--with-dispatcher] [host:port]
#   --with-dispatcher   also run `manage.py run_dispatcher` in the background
#   host:port           bind address (default: 127.0.0.1:8000)
set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

WITH_DISPATCHER=0
ADDR="127.0.0.1:8000"
for arg in "$@"; do
  case "$arg" in
    --with-dispatcher) WITH_DISPATCHER=1 ;;
    *) ADDR="$arg" ;;
  esac
done

docker compose up -d db >/dev/null  # no-op if already running

if [ "$WITH_DISPATCHER" -eq 1 ]; then
  echo "==> Starting event dispatcher in the background..."
  uv run manage.py run_dispatcher &
  DISPATCHER_PID=$!
  trap 'echo; echo "==> Stopping dispatcher..."; kill "$DISPATCHER_PID" 2>/dev/null || true' EXIT
fi

echo "==> Dev server on http://${ADDR}  (tenants at http://<slug>.localhost:${ADDR##*:}/api/docs)"
uv run manage.py runserver "$ADDR"
