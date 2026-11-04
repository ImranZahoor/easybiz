# Easybiz

Multi-tenant, modular ERP core. Domain-agnostic kernel (`easybiz.core`) with
business modules (`easybiz.modules`) that enable per tenant at runtime. Built
to the spec in [`ERP-CORE-SPEC.md`](ERP-CORE-SPEC.md).

## Status

**M6 (Timesheets reference module) — complete.** The first full business module,
proving the module contract end to end: `timesheets_project`/`timesheets_entry`
tables (created only when enabled), `/api/timesheets` endpoints — projects
(read/manage, code uppercased, duplicate → 409) and entries (create with hours
bounds + active-project check, own-vs-all visibility, submit) and review
(approve/reject requiring `entry.approve`, 403 on self-review, `submitted`-only,
publishing `timesheets.entry.approved`/`.rejected` in the same transaction as the
status change + audit); a `core.membership.removed` handler that drops a removed
member's draft time (keeping submitted/approved); the `AttendanceProvider`
capability (approved-hours sum, available only while enabled); default roles
(`timesheet_user`/`timesheet_approver`) and menu. Module API routers now
auto-mount at `/api/<module>` (gated per-tenant by the module-gate middleware).

**M5 (events) — complete.** The transactional outbox now delivers:
`events.publish(name, payload, producer, version)` writes an `OutboxEvent` in the
business transaction (a module publishing an undeclared event raises `EventError`);
`dispatch_pending` locks due pending events (`select_for_update(skip_locked=True)`)
and runs each registered handler in a savepoint, recording an inbox row keyed
`(event_id, "<module>.<func>")` so delivery is at-least-once and idempotent. A
handler whose module is not enabled for the tenant is **parked** and replayed when
the module is enabled; a failing handler retries with exponential backoff
(`min(5·2^attempts, 3600)s`) and dead-letters at `EASYBIZ_EVENT_MAX_ATTEMPTS`. The
`run_dispatcher` command sweeps active tenants. The M3/M4 lifecycle and
membership-removal writes now go through `events.publish`.

**M4 (authentication, authorization, audit & tenant API) — complete.** JWT login
(`POST /api/auth/login`) and `GET /api/auth/me` (identity, permissions, enabled
modules, menu); the `perm()` guard enforcing permission codes (`*` / exact /
`module.*`); the suspended-tenant (403) and module-gate (404) middleware; Swagger
at `/api/docs`; and the `/api/core/*` endpoints — modules (list/enable/disable/
remove-data), roles (list/create), users (list/create/delete), audit. Backed by
`users`/`iam`/`audit` services and the core permission catalogue. Builds on M3
(module system + provisioning) and M0–M2 (skeleton, tenancy/identity, kernel).

Next: **M7** (platform admin API). Multiple auth methods (2FA, magic link,
social/SSO, refresh tokens) are deferred to
**F13**; role inheritance to **F14**; Celery-backed dispatch, delivery leases, and
retention to **F15**.

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
    --owner-email owner@acme.test --owner-password change-me-now --modules timesheets
uv run manage.py tenant_module acme enable demo       # per-tenant enable/disable/remove
uv run manage.py upgrade_modules              # after deploying new module code
uv run manage.py run_dispatcher               # deliver outbox events (add --once for a single sweep)
```

The tenant API is served per tenant host (e.g. `http://acme.localhost:8000/api/`):
`POST /api/auth/login` → token, then `Authorization: Bearer <token>` for
`/api/auth/me` and `/api/core/*`. Interactive docs at `http://<tenant>/api/docs`.

## Conventions

Working conventions (git, packaging, tests, settings, code style) are recorded
in [`ERP-CORE-SPEC.md`](ERP-CORE-SPEC.md) §0.5.
