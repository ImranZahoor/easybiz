#!/usr/bin/env bash
# One-time local setup: database, dependencies, env, and the platform schema.
# Safe to re-run (every step is idempotent).
set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "==> Starting PostgreSQL (docker compose)..."
docker compose up -d db

echo "==> Installing dependencies (uv sync)..."
uv sync

if [ ! -f .env ]; then
  echo "==> Creating .env from .env.example..."
  cp .env.example .env
else
  echo "==> .env already exists; leaving it untouched."
fi

echo "==> Waiting for PostgreSQL to accept connections..."
for i in $(seq 1 30); do
  if docker compose exec -T db pg_isready -U postgres >/dev/null 2>&1; then
    echo "    ready."
    break
  fi
  if [ "$i" -eq 30 ]; then
    echo "PostgreSQL did not become ready in time." >&2
    exit 1
  fi
  sleep 1
done

echo "==> Applying shared (public-schema) migrations..."
uv run manage.py migrate_schemas --shared

echo "==> Initialising the platform tenant and module catalog..."
uv run manage.py init_platform

echo
echo "Setup complete. Next:"
echo "  ./scripts/tenant.sh acme     # provision a test tenant"
echo "  ./scripts/run.sh             # start the dev server"
