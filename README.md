# Easybiz

Multi-tenant, modular ERP core. Domain-agnostic kernel (`easybiz.core`) with
business modules (`easybiz.modules`) that enable per tenant at runtime. Built
to the spec in [`ERP-CORE-SPEC.md`](ERP-CORE-SPEC.md).

## Status

**M3 (module system + provisioning) — complete.** Module catalog + `iam`/`audit`/
`events` models; the module-aware migration mechanism (a module's tables exist in
a tenant schema **only when enabled**); `state.py`, `lifecycle.py` (enable/disable/
remove/upgrade), `capabilities.py`, and a minimal `demo` module (M3a). Plus
**provisioning**: `provision_tenant` creates a tenant end to end (schema, primary
domain, owner user + membership, `owner` role, enabled modules) as an
all-or-nothing operation, with tenant ops (suspend/resume, add/remove domain,
delete) and the `provision_tenant`/`upgrade_modules` CLI (M3b).

Next: **M4** — authentication (JWT) and authorization services (`users/service.py`,
`iam/service.py`, `audit/service.py`), the tenant API (`/api/auth`, `/api/core`),
and activation of the tenant-status + module-gate middleware. Role inheritance
remains deferred to F14 (core roles are flat + wildcards).

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

## Conventions

Working conventions (git, packaging, tests, settings, code style) are recorded
in [`ERP-CORE-SPEC.md`](ERP-CORE-SPEC.md) §0.5.
