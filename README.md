# Easybiz

Multi-tenant, modular ERP core. Domain-agnostic kernel (`easybiz.core`) with
business modules (`easybiz.modules`) that enable per tenant at runtime. Built
to the spec in [`ERP-CORE-SPEC.md`](ERP-CORE-SPEC.md).

## Status

**M2 (kernel core) — complete.** Manifest parsing/validation, version-range
semantics, the module registry (dependency graph, load order, handlers),
discovery, and capability contracts (`AttendanceProvider`) are in place, and the
registry loads + validates module manifests at Django startup. `state.py` and
`capabilities.py` are deferred to **M3** (they depend on the module catalog).
M1 remains: tenancy/identity migrations applied, `init_platform` seeds the
public tenant + `localhost` domain, `/health` answers on the platform host.

Next milestone **M3** adds the module catalog, module-aware migrations, the
per-tenant lifecycle, provisioning, and `state.py`/`capabilities.py` (and
extends `init_platform` to sync the catalog).

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
