#!/usr/bin/env bash
# Provision a tenant for local testing.
#
# Usage: ./scripts/tenant.sh [slug] [modules]
#   slug     tenant slug (default: acme); served at http://<slug>.localhost:8000
#   modules  comma-separated module ids (default: timesheets)
#
# Override the owner via env: OWNER_EMAIL, OWNER_PASSWORD.
set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

SLUG="${1:-acme}"
MODULES="${2:-timesheets}"
EMAIL="${OWNER_EMAIL:-owner@${SLUG}.test}"
PASSWORD="${OWNER_PASSWORD:-change-me-now}"

echo "==> Provisioning tenant '${SLUG}' (modules: ${MODULES})..."
uv run manage.py provision_tenant "${SLUG}" \
  --domain "${SLUG}.localhost" \
  --owner-email "${EMAIL}" \
  --owner-password "${PASSWORD}" \
  --modules "${MODULES}"

echo
echo "Tenant ready:"
echo "  API docs : http://${SLUG}.localhost:8000/api/docs"
echo "  Login    : POST http://${SLUG}.localhost:8000/api/auth/login"
echo "             {\"email\": \"${EMAIL}\", \"password\": \"${PASSWORD}\"}"
echo
echo "If ${SLUG}.localhost does not resolve (e.g. via curl on macOS), add to /etc/hosts:"
echo "  127.0.0.1   ${SLUG}.localhost"
