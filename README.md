# Easybiz

Multi-tenant, modular ERP core. Domain-agnostic kernel (`easybiz.core`) with
business modules (`easybiz.modules`) that enable per tenant at runtime. Built
to the spec in [`ERP-CORE-SPEC.md`](ERP-CORE-SPEC.md).

## Status

**F21c (API conventions — Idempotency-Key) — complete.** A client can now make a tenant-plane `POST`
safely retryable by sending an `Idempotency-Key` header. A per-tenant `idem_key` table
(`easybiz.core.idempotency`) records each keyed request; `IdempotencyMiddleware` (after the tenant/module
middlewares) replays the stored response on a same-key/same-payload retry (with `Idempotency-Replayed:
true`), returns 409 `resource.conflict` while a duplicate is still in flight (one execution, guarded by
the unique key + `select_for_update`), and 422 `idempotency.payload_mismatch` when the key is reused with
a different request. The request hash folds the caller's credential in, so a different caller can never
replay someone else's response; only 2xx responses are cached, and any error releases the key. Absent
header, non-`POST`, and the public/platform schema pass straight through. Expired-row cleanup (a job),
`PUT`/`PATCH`/`DELETE`, and the `/api/v1` move remain later slices.

**F21b (API conventions — error envelope) — complete.** Every error response is now a single envelope
`{"detail", "code", "errors", "request_id"}` across both ninja planes (tenant `api` + `platform_api`) and
the two kernel middlewares (`tenant.suspended` 403, `module.not_enabled` 404) that previously returned a
bare `{"detail"}`. Codes come from Appendix E, defaulted by HTTP status (`easybiz/core/api/envelope.py`);
`DomainError` gained an optional `code`. A ninja `ValidationError` handler turns request-body failures into
`errors: [{field, code, message}]` (`code: validation.failed`). A new first-in-chain `RequestIDMiddleware`
stamps `request.request_id` (an incoming `X-Request-ID`, validated against a short plain-charset allowlist,
or a fresh `uuid4().hex`) and returns it as `X-Request-ID` on every response. Purely additive — `detail` is
unchanged, no endpoint moved, no `/api/v1` yet. `Idempotency-Key`, optimistic concurrency, pagination
`count`, OpenAPI hygiene, the `/api/v1` migration, and finer auth-401 codes remain later F21/F13 slices.

**F23f (agent tooling — MCP wire server, streamable-HTTP) — complete.** The tool layer is now reachable
over the Model Context Protocol at `POST /api/mcp` — a hand-rolled JSON-RPC 2.0 endpoint (no new deps)
supporting `initialize`, `ping`, `tools/list`, and `tools/call`. A transport-free dispatch core
(`easybiz/core/mcp/protocol.py`) turns one message + a `Principal` into one response; the thin
django-ninja route (`easybiz/core/api/mcp_routes.py`) reuses `ToolPrincipalAuth` (JWT or scoped agent
key → `Principal`) and `TenantMainMiddleware`, so the handshake is authenticated and tenant isolation,
the full F23b gate (allowlist → tier/scope → key-subset → `authorize`), and the audit entry are all
inherited unchanged — `tools/call` bottoms out in the same `service._invoke` the HTTP transport uses.
Protocol faults map to JSON-RPC errors; tool-gate denials map to MCP `{content, isError: true}` results.
stdio transport, SSE notifications, the `search_tools`/`describe_tool` meta-toolset, and MCP
resources/prompts are deferred to later slices.

**F23e (agent tooling — response shaping + a composite tool) — complete.** Two more ways to bound an
agent's token cost. A `fields` list on `PageIn` projects each list-tool item to just the requested keys
(`paging_io.project`, lenient — unknown keys absent, `None` returns the full item), applied by
`core.audit.list`, `timesheets.projects.list`, and `timesheets.entries.list`. A pre-aggregated read
composite, `timesheets.overview(start, end, recent)`, returns `{projects, approved_hours,
recent_entries}` in one server-side call — the model neither pages nor sums — composing the existing
`projects_queryset`/`approved_hours`/`entries_queryset` reads and gated like any module tool. Token
bounding for the agent surface is now complete; the MCP wire server, the F23c chatbot (Anthropic SDK),
`admin`-tier elevation, and per-key rate limiting remain.

**F21 (API conventions — cursor pagination, first slice) — complete.** `easybiz/core/api/paging.py`
provides a reusable keyset paginator — `paginate(queryset, *, limit, cursor, order_by)` over
`(order_by field, pk)` with an opaque base64 cursor, `limit` capped at 200, and a 422 on a malformed
cursor — stable under inserts and shared by core and modules. The agent list tools (`core.audit.list`,
`timesheets.projects.list`, `timesheets.entries.list`) now take `limit`/`cursor` and return
`{"items": [...], "next_cursor": ...}`, bounding an agent's output tokens (F23e). The error envelope,
`Idempotency-Key`, optimistic concurrency, OpenAPI hygiene, and the `/api/v1` namespace that brings
pagination to the HTTP list endpoints are later F21 slices; async (202) waits on F11.

**F23b (agent tooling — scoped agent keys + write tools) — complete.** An external agent drives the
tool layer through a **scoped agent key**: F13's `ApiKey` gains `on_behalf_of_user`, a `tool_allowlist`,
and a `read`/`write` `scope`. Tool invocation generalizes to a `Principal` (a user, from the JWT/chatbot
path, or an agent key, from an `Authorization: ApiKey …` transport). The gate: tool ∈ allowlist (deny-all)
→ module enabled (404) → tier ≤ scope (write tools need `write`; `admin` hard-excluded from agents) → the
key's permission subset → the on-behalf user's **`authorize()` (RBAC+ABAC)** → validated inputs → audit
(`actor = key on behalf of user`). Effective authority is the **intersection** of the key's subset and the
user's *current* permissions, so revoking either shrinks the agent instantly. Keys are validated at
creation (`_assert_assignable`; no `*`/unknown/disabled). A `write` tool (`timesheets.projects.create`)
proves the write path. Per-key rate limiting and the MCP stdio/streamable-HTTP wire server remain later
efforts; `admin`-tier elevation + human confirmation too.

**F13 (API keys) — complete.** The first auth-hardening slice: tenant service credentials.
`iam_apikey` stores a public `prefix` + the SHA-256 `secret_hash` (never the secret); `create_api_key`
issues `<prefix>.<secret>` **once**, enforcing that the key's permissions are a **subset of the
creator's** (no escalation); `authenticate_api_key` resolves a credential in constant time
(`hmac.compare_digest`), rejecting revoked/expired keys and stamping `last_used_at`. `/api/core/apikeys`
(under a new `core.apikey.manage`) issues (returns the one-time secret), lists (never the secret), and
revokes. Applying keys as a transport auth (on-behalf-of user, tool allowlist, read/write scope, per-key
rate limit) + the MCP wire server is F23b; the rest of F13 (refresh, reset, invitations, MFA, SSO,
signing keys, brute-force, password policy) are separate slices (some blocked on F9/F5).

**F23d (agent tooling — per-module tool contributions) — complete.** Modules now contribute their
own tools to the registry via a `<module>/tools.py` (imported at startup alongside `handlers`/
`providers`). A `Tool` carries an optional `module_id`; `tools.service` gates a module tool by that
module's per-tenant enablement — a disabled module's tools are neither listed nor invocable (a clean
404, checked before the perm gate, so it never leaks which tools a disabled module has). Timesheets
contributes `timesheets.projects.list` / `timesheets.entries.list` (own-vs-all like its HTTP endpoint).
The F17 contract kit gains `check_tools` — every module tool must be name-prefixed `<id>.`, use a
declared (or `core.*`) permission, and carry a valid tier — run by `check_module`/`pytest -m
module_contract`.

**F23a (agent tooling — read-only tool registry + HTTP transport) — complete.** The first slice of
F23: a transport-agnostic tool layer. `easybiz/core/tools/` holds a `Tool` (name, description, risk
tier `read`/`write`/`admin`, the same `perm()` code as the matching HTTP endpoint, `idempotent`, input
schema, handler wrapping an existing query) and a registry; `tools.service.invoke()` enforces the tool's
`perm()` against the caller's effective iam permissions (the exact HTTP gate — nothing bypasses it),
refuses non-`read` tools (write/admin need an agent key — F13), pydantic-validates inputs, and audits
every call. Six core read tools (context, modules, roles, permissions, users, audit) are registered at
startup. `/api/tools` (tenant-JWT authed) gives lazy discovery — `GET /tools?q=` (compact, perm-filtered
so unauthorized tools never appear), `GET /tools/{name}` (input schema), `POST /tools/{name}/invoke`.
The MCP wire protocol, scoped agent keys + write tools, the integrated chatbot, per-module tool
contributions, and response shaping are later F23 slices (paired with F13/F21).

**F17d (module system v2 — scaffold, uninstall, runbook) — complete. F17 is done.**
`python manage.py startmodule <id> [--requires ..] [--optional ..] [--path ..]` scaffolds a
worked-sample, contract-clean module (sample model + templated initial migration, a guarded
endpoint, a default role, and its own contract test), validates the id, never overwrites an
existing directory, and appends the package to `.env`'s `EASYBIZ_MODULES`.
`python manage.py uninstall_module <id>` removes a module from the catalog (its `Module` +
`Permission` rows), refusing while any tenant still holds a `TenantModule` row; code removal
stays a deploy step. The rolling module-deploy runbook is at
[`docs/runbooks/module-deploy.md`](docs/runbooks/module-deploy.md) (note the D9 limit: new
module code needs a restart; enable/disable is instant).

**F17c (module system v2 — contract test kit) — complete.** `easybiz/core/testing` provides
`module_harness(module_id, with_=, without=)` (a throwaway tenant with the module + hard deps, torn
down after) and `run_module_contract_checks(module_id)` — eleven checks that a module obeys the module
contract: manifest/app-label, endpoint permissions declared (Ninja introspection), subscriptions have
handlers, no cross-module imports (AST scan), no cross-module FKs + table prefix (`_meta`), migrations
reversible, lifecycle enable/disable/remove/re-enable, schema isolation, handler wiring, optional-dep
matrix, and the gate answering 404 when disabled. `python manage.py check_module <id>` prints failures
(nonzero exit on any); `pytest -m module_contract` runs the suite against `timesheets`/`demo` (both
green) with negative tests breaking each rule. Pragmatic depth: payload-schema matching defers to F15.

**F17b (module system v2 — extension points) — complete.** The multi-provider sibling of
capabilities: `easybiz/core/kernel/extensions.py` offers `register(point, impl, module_id)` (many
contributors per point) and `contributors(point)` — every contributor whose module is enabled for the
current tenant, in dependency/load order, semantics-free (the host module decides all-pass / collect /
first-wins). The registry validates the manifest `extension_points`/`extends` declarations F17a parses:
a point's contract must be real, point names are unique, and an `extends` must name a declared point of a
module it `requires`/`optional`s at a compatible version. The `demo` module (now v2) hosts a trivial
`demo.greeters` point (contract `DemoGreeter`) with a `greetings.all_greetings()` fan-out, proving the
host→contributor path. A module is the plugin unit — there is no separate plugin subsystem.

**F17a (module system v2 — manifest v2, validation gaps, capability versioning) — complete.**
Manifests gain `manifest_version: 2` with versioned `provides`/`consumes` (`{contract, version}` /
`{contract, range, optional}`), `requires_core` (a semver range checked against the new
`EASYBIZ_CORE_VERSION`), `extension_points`/`extends` declarations (runtime arrives in F17b), and a
`sensitive` flag on permissions — all backward compatible with v1 (bare-string `provides`/`consumes`).
Validation is hand-rolled in `parse_manifest` (no new dependency); `easybiz/core/kernel/manifest.schema.json`
is the published contract, kept honest by a sync test. The registry now closes the three validation gaps
(`provides`/`consumes` must name real contracts; a declared `provides` must actually be registered; a
non-optional `consumes` must be satisfied by a required module) and enforces `requires_core`. Capability
resolution is version-aware: `capabilities.register(contract, impl, module_id, version)` and
`get(contract, range=…)` treat an out-of-range provider as unavailable (logged). Timesheets adopts v2 and
declares its `AttendanceProvider`; `demo` stays v1.

**F14b (authorization v2 — ABAC) — complete.** Attribute-based policies layer on top of
F14a's RBAC: tenant tables `iam_policy` (`allow_if`/`deny_if` rules with a declarative
condition tree — operators `eq/ne/lt/lte/gt/gte/in/and/or/not` over `subject.*`/`resource.*`/
`context.*`, **never** evaluated as code, depth/node-count capped) and `iam_userattribute`
(subject attributes like `approval_limit`). `authorize(user, perm, resource, context)` runs
**after** the `perm()` RBAC gate (RBAC must grant first → any matching `deny_if` denies → if
any `allow_if` exists at least one must match), reading policies/attributes through the F14a
version-keyed cache (policy/attribute changes bump it). `/api/core/policies` (CRUD +
`POST /policies/evaluate` dry-run) and `/api/core/users/{id}/attributes` sit under a new
`core.policy.manage`; invalid conditions are rejected on save (422). Demonstrated by gating
timesheet approval on the approver's `approval_limit` vs the entry's hours. Org-scope row
filtering remains **F3**.

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
