# Easybiz

Multi-tenant, modular ERP core. Domain-agnostic kernel (`easybiz.core`) with
business modules (`easybiz.modules`) that enable per tenant at runtime. Built
to the spec in [`ERP-CORE-SPEC.md`](ERP-CORE-SPEC.md).

## Status

**M3a (module system core) — complete.** The module catalog (`catalog_*`) and the
`iam`/`audit`/`events` models exist; the module-aware migration mechanism creates
a module's tables in a tenant schema **only when enabled** (router + per-schema
migrate); `state.py` reports enabled modules; `lifecycle.py` enables/disables/
removes/upgrades modules (seeding roles, writing audit + outbox rows directly to
the models — services arrive M4/M5); `capabilities.py` resolves a contract only
while its provider is enabled; a minimal `demo` module is the enable target; the
`sync_modules`/`tenant_module` commands work; and `init_platform` now syncs the
catalog.

Next: **M3b** — provisioning (`provision_tenant`, all-or-nothing) + tenant ops
(suspend/resume, domains, delete) + the `provision_tenant`/`upgrade_modules` CLI.
Until then, tenants are created directly (as the tests do). Role inheritance is
deferred to F14 (core roles are flat + wildcards).

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
```

## Conventions

Working conventions (git, packaging, tests, settings, code style) are recorded
in [`ERP-CORE-SPEC.md`](ERP-CORE-SPEC.md) §0.5.
