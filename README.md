# Easybiz

Multi-tenant, modular ERP core. Domain-agnostic kernel (`easybiz.core`) with
business modules (`easybiz.modules`) that enable per tenant at runtime. Built
to the spec in [`ERP-CORE-SPEC.md`](ERP-CORE-SPEC.md).

## Status

**M0 (skeleton) — complete.** The project boots and `uv run manage.py check`
passes. No migrations are authored yet and no endpoints are served beyond
`/health` on the platform host. Next milestone **M1** authors the tenancy and
identity migrations and the `init_platform` bootstrap.

## Prerequisites

- Python 3.13 (pinned via `.python-version`), managed with [`uv`](https://docs.astral.sh/uv/)
- Docker (for local PostgreSQL 16)

## Setup

```bash
docker compose up -d db          # PostgreSQL 16 on localhost:5432 (db "easybiz")
uv sync                          # install deps into .venv
cp .env.example .env             # adjust secrets/hosts per environment
uv run manage.py check           # system checks must pass
```

## Common commands

```bash
uv run manage.py check                        # Django system checks
uv run pytest                                 # test suite (uses db "easybiz_test")
uv run ruff check . && uv run ruff format --check .   # lint + format
uv run mypy easybiz config                    # type-check
uv run manage.py makemigrations --check --dry-run     # pending migrations (M1 onward)
```

## Conventions

Working conventions (git, packaging, tests, settings, code style) are recorded
in [`ERP-CORE-SPEC.md`](ERP-CORE-SPEC.md) §0.5.
