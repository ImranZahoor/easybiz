# Easybiz

Multi-tenant, modular ERP core. Domain-agnostic kernel (`easybiz.core`) with
business modules (`easybiz.modules`) that enable per tenant at runtime. Built
to the spec in [`ERP-CORE-SPEC.md`](ERP-CORE-SPEC.md).

## Status

**M4 (authentication, authorization, audit & tenant API) — complete.** JWT login
(`POST /api/auth/login`) and `GET /api/auth/me` (identity, permissions, enabled
modules, menu); the `perm()` guard enforcing permission codes (`*` / exact /
`module.*`); the suspended-tenant (403) and module-gate (404) middleware; Swagger
at `/api/docs`; and the `/api/core/*` endpoints — modules (list/enable/disable/
remove-data), roles (list/create), users (list/create/delete), audit. Backed by
`users`/`iam`/`audit` services and the core permission catalogue. Builds on M3
(module system + provisioning) and M0–M2 (skeleton, tenancy/identity, kernel).

Next: **M5** (the events dispatcher — `events/service.publish`/`dispatch_pending`
+ `run_dispatcher`) and **M6** (the real Timesheets module). Multiple auth methods
(2FA, magic link, social/SSO, refresh tokens) are deferred to **F13**; role
inheritance to **F14**.

## Prerequisites

- Python 3.13 (pinned via `.python-version`), managed with [`uv`](https://docs.astral.sh/uv/)
- Docker (for local PostgreSQL 16)

## Setup

```bash
docker compose up -d db          # PostgreSQL 16 on localhost:5432 (db "easybiz") — required for tests
uv sync                          # install deps into .venv
cp .env.example .env             # adjust secrets/hosts per environment
uv run manage.py check           # system checks must pass
uv run manage.py migrate_schemas --shared   # apply shared migrations to the public schema
uv run manage.py init_platform              # create the public tenant + localhost domain
```

## Common commands

```bash
uv run manage.py check                        # Django system checks
uv run pytest                                 # test suite (uses db "easybiz_test")
uv run ruff check . && uv run ruff format --check .   # lint + format
uv run mypy easybiz config                    # type-check
uv run manage.py makemigrations --check --dry-run     # verify no un-authored migrations

uv run manage.py sync_modules                 # record on-disk modules in the catalog
uv run manage.py provision_tenant acme --domain acme.localhost \
    --owner-email owner@acme.test --owner-password change-me-now --modules demo
uv run manage.py tenant_module acme enable demo       # per-tenant enable/disable/remove
uv run manage.py upgrade_modules              # after deploying new module code
```

The tenant API is served per tenant host (e.g. `http://acme.localhost:8000/api/`):
`POST /api/auth/login` → token, then `Authorization: Bearer <token>` for
`/api/auth/me` and `/api/core/*`. Interactive docs at `http://<tenant>/api/docs`.

## Conventions

Working conventions (git, packaging, tests, settings, code style) are recorded
in [`ERP-CORE-SPEC.md`](ERP-CORE-SPEC.md) §0.5.
