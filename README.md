# Easybiz

Multi-tenant, modular ERP core. Domain-agnostic kernel (`easybiz.core`) with
business modules (`easybiz.modules`) that enable per tenant at runtime. Built
to the spec in [`ERP-CORE-SPEC.md`](ERP-CORE-SPEC.md).

## Status

**F14a (authorization v2 — roles) — complete.** Part B begins here: full role
administration — `GET`/`PATCH`/`DELETE`/`clone` roles, `PUT`/`POST`/`DELETE` user-role
assignment, `GET /core/permissions` (grouped by module), `GET /core/roles/{id}` (parent +
effective permissions) — plus **role inheritance** (a role's permissions are the union with
its ancestors', cycle-guarded), the guards (no define- or assign-time privilege escalation,
last-`owner` protection, system-role lock), a `core.role.changed` event on every change, and
a version-counter permission cache on the auth path. ABAC and org-scope remain **F14b / F3**.

**M7 (platform admin API) — complete.** The operator plane on the public host:
`PlatformJWTAuth` (public-host-only, `scope="platform"` tokens, `is_platform_admin`
read live so demotion is immediate), throttled `POST /api/platform/auth/login`, and
`/api/platform/*` — overview, tenants (list/detail/create/rename/suspend/resume/delete,
with all-or-nothing provisioning and `confirm_slug` delete), domains, per-tenant module
toggles, the module catalog with `sync`/`upgrade`, platform admins (add/promote/remove
with self + last-admin guards) and the platform audit log. Every mutation is recorded via
`record_platform` (`tenancy_platformauditlog`). Bootstrap with `create_platform_admin`;
platform docs at `http://localhost:8000/api/platform/docs`.

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

**M8 (CORS) — complete.** `CorsMiddleware` runs first so preflights are answered
before tenant/module resolution (no token or enabled module required); actual and
error responses carry CORS headers; `EASYBIZ_CORS_ORIGINS` sets allowed origins and,
in `DEBUG`, `localhost`/`*.localhost`/`127.0.0.1` on any port are allowed while unknown
origins are not. Credentials are off (Bearer tokens). (The module-app "unapplied
migration" notice was already resolved in the migrate command.)

**Part A (M0–M9) — complete and verified.** The full gate is green — `uv run pytest`
(217 on real PostgreSQL), `manage.py check`, `makemigrations --check`, `ruff`, `mypy` —
and a live end-to-end operator run passes: create a platform admin, create a tenant over
HTTP, the owner logs in on the tenant host, enable a module, suspend (tenant login then
403), and delete (schema dropped, 404 after) — every step audited in order.

**Part B** (F1–F22) is underway, foundations first: **F14a done** → next **F14b** (ABAC) and
**F17** (module system v2), then settings/flags, events v2, jobs, and eventually HR/Payroll
(F1/F2) on the hardened base. **F23** (agent tooling: MCP + chatbot) is planned after F14.
Multiple auth methods (2FA, magic link, social/SSO) are **F13**; Celery-backed dispatch to **F15**.

## Prerequisites

- Python 3.13 (pinned via `.python-version`), managed with [`uv`](https://docs.astral.sh/uv/)
- Docker (for local PostgreSQL 16)

## Setup

Quick path — the scripts in `scripts/` wrap the steps below (all idempotent):

```bash
./scripts/setup.sh               # db up, deps, .env, shared migrations, platform tenant + catalog
./scripts/tenant.sh acme         # provision a test tenant at acme.localhost (modules: timesheets)
./scripts/run.sh                 # dev server; add --with-dispatcher to also deliver outbox events
```

Then open `http://acme.localhost:8000/api/docs`, log in as `owner@acme.test` / `change-me-now`,
click **Authorize** with the returned token, and exercise `/api/core/*` and `/api/timesheets/*`.
`./scripts/tenant.sh <slug> <modules>` provisions other tenants (override the owner via
`OWNER_EMAIL`/`OWNER_PASSWORD`).

The equivalent manual steps:

```bash
docker compose up -d db          # PostgreSQL 16 on localhost:5432 (db "easybiz") — required for tests
uv sync                          # install deps into .venv
cp .env.example .env             # adjust secrets/hosts per environment
uv run manage.py check           # system checks must pass
uv run manage.py migrate_schemas --shared   # apply shared migrations to the public schema
uv run manage.py init_platform              # create the public tenant + localhost domain + module catalog
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
uv run manage.py create_platform_admin --email ops@easybiz.test --password change-me-now  # bootstrap operator
```

The tenant API is served per tenant host (e.g. `http://acme.localhost:8000/api/`):
`POST /api/auth/login` → token, then `Authorization: Bearer <token>` for
`/api/auth/me` and `/api/core/*`. Interactive docs at `http://<tenant>/api/docs`.

The platform (operator) API is served on the platform host (`http://localhost:8000`):
`POST /api/platform/auth/login` → token, then `/api/platform/*` (tenants, domains,
modules, admins, audit). Docs at `http://localhost:8000/api/platform/docs`. Create the
first operator with `create_platform_admin`.

## Conventions

Working conventions (git, packaging, tests, settings, code style) are recorded
in [`ERP-CORE-SPEC.md`](ERP-CORE-SPEC.md) §0.5.
