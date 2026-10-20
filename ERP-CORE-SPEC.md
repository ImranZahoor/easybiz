# ERP Core: Architecture and Build Specification

| | |
|---|---|
| **Document** | `ERP-CORE-SPEC.md`, version 1.0 |
| **Audience** | Claude Code (and human engineers) |
| **Purpose** | (A) rebuild the current, working modular ERP core exactly; (B) build the remaining features on top of it |
| **Status of Part A** | Implemented and tested: 85 tests passing against PostgreSQL |
| **Status of Part B** | Planned. Specified feature by feature in sections 13 to 22 |

---

## 0. How to use this document (instructions for the coding agent)

### 0.1 Structure

- **Part A (sections 1 to 12)** describes the baseline that exists today. Rebuild it milestone by milestone (section 11). Every statement in Part A was verified against a running system.
- **Part B (sections 13 to 22 and the appendices)** specifies features that do not exist yet, in build order, each with acceptance criteria.

### 0.2 Working rules

1. **Work one milestone or feature at a time.** Finish its acceptance criteria before starting the next. Commit after each.
2. **Tests are part of the deliverable.** Each milestone and feature lists tests. Run the whole suite before declaring anything done: `pytest`. Never leave the suite red.
3. **Treat the invariants (section 2.3) as law.** If a feature seems to need breaking one, stop and propose a spec change instead.
4. **Prefer the smallest change** that satisfies the acceptance criteria. Do not refactor unrelated code.
5. **When a library behaves differently from this document, the library wins.** Fix the code, then record the finding in the decisions and pitfalls log (section 12).
6. **Keep `README.md` in sync** with any command, endpoint, setting or behaviour you add.
7. **Generate migrations with `makemigrations`; never hand-write them.** Commit them.
8. **Verify with the real database.** Tests run against real PostgreSQL. Do not replace it with SQLite or mocks.
9. **Ask before destructive design changes** (dropping tables, changing public API shapes, changing token formats).

### 0.3 Definition of done (applies to every milestone and feature)

- [ ] All acceptance criteria in its section are met.
- [ ] New and existing tests pass (`pytest`), including isolation tests when tenant data is touched.
- [ ] `python manage.py check` and `python manage.py makemigrations --check --dry-run` are clean.
- [ ] New endpoints appear in the OpenAPI docs with correct auth and error responses.
- [ ] Sensitive actions write an audit record (tenant audit or platform audit).
- [ ] New permissions, events, settings and commands are declared in the right catalogue (manifest, appendix C/D/B).
- [ ] README updated.

### 0.4 Conventions

- **Language and style:** Python 3.12+, type hints on public functions, small modules, docstrings that explain *why*.
- **IDs:** business entities use UUID primary keys (`uuid4`). Infrastructure join tables use `BigAutoField`. Human-readable numbers (invoice numbers and similar) come from numbering series (F7), never from primary keys.
- **Time:** store UTC (`USE_TZ = True`). APIs exchange ISO 8601.
- **Errors:** JSON `{"detail": "<message>"}`. Status codes: 400 missing confirmation, 401 unauthenticated, 403 forbidden or suspended, 404 not found or module not enabled, 409 state conflict, 422 validation, 429 throttled.
- **Naming:** module ids lowercase with underscores; permissions `<module>.<resource>.<action>`; events `<module>.<entity>.<past-tense-verb>`; tables prefixed with the module id (`timesheets_entry`).
- **Management command names must not collide** with django-tenants commands (it ships `create_tenant`, `create_tenant_superuser`, `clone_tenant`, `migrate_schemas`, and others).

### 0.5 Agent working conventions (binding)

These apply to every milestone and feature. They override any conflicting default behaviour of the harness.

**Version control**

- Commit messages are short: one imperative line, ~50 characters. Add a body only to explain *why*, never to restate the diff.
- **Never** add co-author trailers, "Generated with" lines, emojis, or any tool/assistant attribution to commits or PRs.
- PR descriptions use this template — terse bullets, no filler, no marketing language:
  ```
  ## What
  <the change, one or two lines>
  ## How
  <approach; key files and decisions>
  ## Acceptance
  <how to verify; which acceptance criteria / tests are met>
  ```

**Code layout**

- Types stay out of logic files. Request/response schemas and type definitions live in their own module, `types.py`; `api.py` imports them and holds only routers and handlers. Reinforces "small modules" in §0.4.
- Comments: no narration of *what* the code does. Add a single-line comment only where the *why* is not obvious from the code.
- Docstrings: every public class and function carries a docstring, especially API handlers — Django Ninja surfaces them into the OpenAPI docs. The docstring states intent/behaviour, not the signature.
- Apply **DRY** and **SOLID** where they genuinely fit; do not force an abstraction before there is real duplication or a real axis of change.

**Tooling**

- Python and packages are managed with **`uv`** (already installed): `pyproject.toml` + `uv.lock`. Add dependencies with `uv add`, run everything with `uv run` (`uv run pytest`, `uv run manage.py ...`), sync with `uv sync`. Do **not** use `pip` or `requirements*.txt`.
- Tests use **`pytest`** (no pytest-django, per P11).

**Test and fixture placement**

- Global, cross-cutting fixtures live in the top-level `tests/conftest.py`; cross-cutting and core tests live under `tests/`.
- Each module owns its tests and fixtures: test files in `easybiz/modules/<id>/tests/`, and the module's `conftest.py` at the **package root** (`easybiz/modules/<id>/conftest.py`), *not* inside its `tests/` folder. Pytest still applies that conftest to everything under the package, and keeping it at the root avoids import collisions.
- `pytest.ini` `testpaths` includes both `tests` and `easybiz.modules`.

**Settings and configuration**

- One Django settings file (`config/settings.py`). Do **not** split it by environment and do **not** create per-environment settings modules.
- Environment differences come from a `.env` file per environment, loaded at startup — not from separate settings modules.
- Modules do **not** get their own Django settings: Django loads exactly one settings module per process and all modules share it. A module configures itself through (a) its manifest-declared settings schema and defaults (F5) plus per-tenant stored values, and (b) module-local constants in its own package. It joins the shared config only through `EASYBIZ_MODULES` discovery (§5.3).

---

## 1. Purpose, scope and glossary

### 1.1 Purpose

Build a **small, domain-agnostic ERP kernel** with platform services (tenancy, identity, authorization, audit, events), onto which business applications such as supply chain, HR, payroll and timesheets plug in as **modules**. Modules can be installed system-wide, enabled and disabled **per tenant at runtime**, and must work **independently and together**.

### 1.2 In scope (Part A, built)

Schema-per-tenant multi-tenancy; global identity with per-tenant memberships; JWT authentication; role-based authorization with permission catalog; audit log; transactional outbox events; capability interfaces; module manifests, registry and lifecycle; per-tenant module tables; tenant API; platform admin API; one reference module (Timesheets); CORS; interactive API docs.

### 1.3 Out of scope for the core (belongs in modules)

Any business logic: stock, invoices, payroll rules, leave policies and so on. The core must never import a module.

### 1.4 Glossary

| Term | Meaning |
|---|---|
| **Tenant** | One customer organisation. Owns one PostgreSQL schema (`t_<slug>`) and one or more domains |
| **Platform** | The operator of the whole system. Served on the *platform host* using the `public` schema |
| **Platform host** | Host name mapped to the `public` tenant (`localhost` in development). Serves `/health` and `/api/platform/` only |
| **Tenant host** | A domain mapped to a tenant (`acme.localhost`). Serves the tenant API |
| **Module** | A Python package with a manifest, a Django app, models, API router and optional handlers and providers |
| **Installed** | Module code is deployed and recorded in the catalog (`catalog_module`). System-wide |
| **Enabled** | A tenant uses the module: tables exist in its schema and its routes answer |
| **Manifest** | `manifest.json` in a module package. Declares permissions, events, dependencies, menu, roles |
| **Capability** | A versioned Python `Protocol` in `easybiz/core/contracts.py` that one module can provide and another can request |
| **Outbox** | Table of events written in the same transaction as the business change, delivered later |
| **Gate** | Middleware that answers 404 for routes of modules a tenant has not enabled |

---

## 2. Architecture

### 2.1 Layers

```
┌───────────────────────────────────────────────────────────────────┐
│ Clients: web app · mobile/scanners · external systems (API keys)  │
├───────────────────────────────────────────────────────────────────┤
│ REQUEST PIPELINE (Django ASGI + Django Ninja)                     │
│  CORS → tenant resolution → tenant status → module gate →         │
│  authentication → authorization → router → audit/outbox in txn    │
├───────────────────────────────────────────────────────────────────┤
│ BUSINESS MODULES (packages in easybiz/modules/*, enabled per tenant)  │
│  timesheets · (hr · payroll · scm ...)                            │
├───────────────────────────────────────────────────────────────────┤
│ CORE                                                              │
│  Kernel: manifest loader · registry · lifecycle · capability      │
│          registry · event bus · tenant manager · migrate hooks    │
│  Platform services: tenancy · identity · authorization · audit ·  │
│          (later: org · master data · settings · workflow · ...)   │
├───────────────────────────────────────────────────────────────────┤
│ DATA: PostgreSQL (schema public + schema per tenant) · Redis/     │
│       broker (later) · object storage (later) · IdP (later)       │
└───────────────────────────────────────────────────────────────────┘
```

### 2.2 Schema layout

- **`public` schema** (shared): `tenancy_tenant`, `tenancy_domain`, `tenancy_platformauditlog`, `users_user`, `users_membership`, `catalog_module`, `catalog_tenantmodule`, `catalog_permission`, `django_content_type`, `django_migrations`.
- **Tenant schema `t_<slug>`**: core tables `iam_role`, `iam_rolepermission`, `iam_userrole`, `audit_auditlog`, `events_outboxevent`, `events_inboxprocessed`, plus the tables of **only those modules the tenant has enabled** (for example `timesheets_project`, `timesheets_entry`).
- Tenant queries run with `search_path = t_<slug>, public`, so public tables remain reachable by name.

### 2.3 Invariants (must always hold)

| # | Invariant |
|---|---|
| **I1** | The core knows no business domain. Modules import only `easybiz.core.*`, never another module |
| **I2** | No foreign keys across module boundaries, and none from tenant schemas to public tables. Reference by UUID value (`user_id`, `employee_id`) |
| **I3** | Tenant data lives only in the tenant schema. Platform catalog data lives only in `public` |
| **I4** | A module's tables exist only in schemas of tenants that have a `catalog_tenantmodule` row for it. Enforced by both the DB router and the per-schema migrate hook (section 5.5) |
| **I5** | Routes of every installed module are mounted; the module gate hides them from tenants that have not enabled the module |
| **I6** | Events are published only inside the business transaction (outbox). Delivery is at-least-once. Handlers are idempotent through the inbox keyed by `(event_id, handler key)` |
| **I7** | A capability resolves only if its provider's module is enabled for the current tenant. `optional=True` returns `None` instead of raising |
| **I8** | Permission codes are declared in a manifest, prefixed with the module id; core codes start with `core.` |
| **I9** | Tenant tokens are bound to the tenant of the request host. Platform tokens (`scope: platform`) and tenant tokens are not interchangeable |
| **I10** | Every sensitive action writes an audit record (tenant audit for tenant actions, platform audit for platform actions) |
| **I11** | Destructive operations require explicit confirmation and preconditions (disabled first, suspended first, `confirm` flags) |
| **I12** | `migrate_schemas` resets the DB connection to `public`. Any code that calls it must restore the previous tenant afterwards |
| **I13** | Inside `schema_context()` the connection holds a *stub* tenant without a primary key. Code that needs the real tenant must resolve it from `schema_name` (`kernel/state.py::_resolve`) |
| **I14** | Provisioning a tenant is all-or-nothing: validate first, roll back everything (schema included) on any failure |
| **I15** | Tests run against real PostgreSQL. No SQLite, no database mocks |

### 2.4 Request lifecycle (tenant host)

1. `CorsMiddleware` answers browser preflights and adds CORS headers (before anything else, so errors also carry them).
2. `TenantMainMiddleware` (django-tenants) maps the host to a tenant, sets `request.tenant`, switches `search_path`. Unknown host gives 404.
3. `TenantStatusMiddleware`: tenant `is_active = False` gives 403 `"This tenant is suspended"` for every path.
4. `ModuleGateMiddleware`: path `/api/<module_id>/...` where `<module_id>` is an installed module and the module is not enabled for the tenant gives 404.
5. Ninja endpoint: `TenantJWTAuth` validates the Bearer token (signature, expiry, `tenant` claim equals host tenant, user active, active membership), then checks the endpoint's permission if one is declared (403 on failure).
6. Handler runs inside `transaction.atomic()` for writes; it writes audit rows and outbox events in that same transaction.

### 2.5 Hosts and URL configurations

| Host kind | URL conf | Serves |
|---|---|---|
| Platform host (public tenant) | `config/urls_public.py` | `/health`, `/api/platform/*` (platform API and its docs) |
| Tenant host | `config/urls.py` | `/api/auth/*`, `/api/core/*`, `/api/<module>/*`, `/api/docs` |

The tenant API does not exist on the platform host, and the platform API does not exist on tenant hosts (both answer 404).

---

## 3. Technology and repository

### 3.1 Stack

| Concern | Choice |
|---|---|
| Language | Python 3.12+ (tested on 3.12 and 3.13) |
| Framework | Django (tested on 6.1; requirement `>=5.2`) |
| Multi-tenancy | `django-tenants` (tested 4.0; `>=3.8`) |
| API | `django-ninja` (tested 1.7; `>=1.7`, needs `Status` and throttling) |
| Database | PostgreSQL 16 via `psycopg[binary]` 3.x |
| Packaging | `uv` (`pyproject.toml` + `uv.lock`); no `pip`, no `requirements*.txt` (§0.5) |
| Auth tokens | `PyJWT` (HS256 today; see F13 for RS256 and rotation) |
| CORS | `django-cors-headers` |
| Tests | `pytest` (pytest-django is **not** used; see P11) |
| Dev database | `docker-compose.yml` with `postgres:16` |

### 3.2 Repository layout

```
easybiz/
├── README.md
├── ERP-CORE-SPEC.md                 (this file)
├── manage.py
├── pyproject.toml / uv.lock         (managed with uv; no pip, no requirements*.txt — §0.5)
├── docker-compose.yml               (postgres:16, db "easybiz", user/password postgres)
├── pytest.ini                       (testpaths = tests easybiz, addopts = -q -p no:django)
├── config/
│   ├── settings.py
│   ├── urls.py                      (tenant API)
│   ├── urls_public.py               (health + platform API)
│   └── asgi.py
├── easybiz/                         (namespace package: easybiz.core, easybiz.modules)
│   ├── core/
│   │   ├── contracts.py             (capability Protocols)
│   │   ├── tenancy/    models: Tenant, Domain, PlatformAuditLog · audit.py
│   │   ├── users/      models: User, Membership · service.py
│   │   ├── catalog/    models: Module, TenantModule, Permission
│   │   ├── iam/        models: Role, RolePermission, UserRole · service.py
│   │   ├── audit/      models: AuditLog · service.py
│   │   ├── events/     models: OutboxEvent, InboxProcessed · service.py
│   │   ├── kernel/
│   │   │   ├── manifest.py          parse and validate manifest, version ranges
│   │   │   ├── registry.py          module registry, dependency graph, handlers, @subscribe
│   │   │   ├── discovery.py         settings list + entry points "easybiz.modules"
│   │   │   ├── state.py             enabled-module lookups, stub-tenant resolver
│   │   │   ├── capabilities.py      capability registry
│   │   │   ├── routers.py           DB router (module tables only where enabled)
│   │   │   ├── migrate.py           per-schema migrate command (hides absent modules)
│   │   │   ├── middleware.py        ModuleGateMiddleware, TenantStatusMiddleware
│   │   │   ├── lifecycle.py         install / enable / disable / remove / upgrade
│   │   │   ├── provisioning.py      provision_tenant (all-or-nothing)
│   │   │   ├── tenants.py           validation, suspend/resume, domains, delete
│   │   │   ├── core_permissions.py  core permission catalogue
│   │   │   ├── apps.py              loads registry at startup
│   │   │   └── management/commands/ init_platform, sync_modules, provision_tenant,
│   │   │                            tenant_module, upgrade_modules, run_dispatcher,
│   │   │                            create_platform_admin, runserver (override)
│   │   ├── api/                     tenant API: auth.py (JWT, perm()), core_routes.py
│   │   └── platform_api/            platform API: auth.py, tenants.py, modules.py, admins.py
│   └── modules/
│       └── timesheets/              manifest.json, apps.py, models.py, types.py, api.py,
│                                    handlers.py, providers.py, conftest.py, migrations/, tests/
└── tests/                           global conftest.py + cross-cutting/core tests (section 10);
                                     module-specific tests live in easybiz/modules/<id>/tests/ (§0.5)
```

### 3.3 Settings reference

| Setting / env var | Default | Meaning |
|---|---|---|
| `DJANGO_SECRET_KEY` | dev-only string (32+ chars) | Signs JWTs. **Must be set in production** |
| `DJANGO_DEBUG` | `1` | `1` also enables the permissive localhost CORS regexes |
| `DJANGO_ALLOWED_HOSTS` | `.localhost,127.0.0.1` | Comma separated |
| `EASYBIZ_DB_NAME` / `_USER` / `_PASSWORD` / `_HOST` / `_PORT` | `easybiz` (`easybiz_test` under pytest) / `postgres` / `postgres` / `localhost` / `5432` | Database |
| `EASYBIZ_MODULES` (settings list) | `["easybiz.modules.timesheets"]` | Explicit module packages; entry point group `easybiz.modules` is merged in |
| `EASYBIZ_JWT_TTL_SECONDS` | `3600` | Tenant token lifetime |
| `EASYBIZ_PLATFORM_JWT_TTL_SECONDS` | `1800` | Platform token lifetime |
| `EASYBIZ_PLATFORM_LOGIN_RATE` | `10/m` | Per client IP throttle on platform login |
| `EASYBIZ_EVENT_MAX_ATTEMPTS` (settings) | `5` | Attempts before an event is dead-lettered |
| `EASYBIZ_CORS_ORIGINS` | empty | Comma separated allowed origins (production) |
| `TENANT_SYNC_ROUTER` | `easybiz.core.kernel.routers.ModuleAwareTenantSyncRouter` | Required by django-tenants checks |
| `TENANT_BASE_MIGRATE_COMMAND` | `easybiz.core.kernel.migrate.Command` | Hides absent modules per schema |
| `STATIC_URL` / `STATIC_ROOT` | `/static/` / `staticfiles` | Needed for Swagger UI assets |
| `PASSWORD_HASHERS` | PBKDF2 only | `django.contrib.auth` is not installed; only hashers are used |

### 3.4 Installed apps (order matters)

```python
SHARED_APPS = [
    "django_tenants",                 # must be first
    "easybiz.core.kernel",                # early so its runserver override beats staticfiles' (P1)
    "django.contrib.contenttypes",    # required by django-tenants
    "django.contrib.staticfiles",     # Swagger UI assets
    "easybiz.core.tenancy", "easybiz.core.users", "easybiz.core.catalog",
    "ninja",                          # templates for /api/docs
    "corsheaders",
]
TENANT_APPS = ["easybiz.core.iam", "easybiz.core.audit", "easybiz.core.events", *EASYBIZ_MODULE_PACKAGES]
INSTALLED_APPS = list(SHARED_APPS) + [a for a in TENANT_APPS if a not in SHARED_APPS]
AUTH_USER_MODEL = "users.User"      # custom user; django.contrib.auth is NOT installed
MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django_tenants.middleware.main.TenantMainMiddleware",
    "easybiz.core.kernel.middleware.TenantStatusMiddleware",
    "easybiz.core.kernel.middleware.ModuleGateMiddleware",
    "django.middleware.common.CommonMiddleware",
]
TEMPLATES = [DjangoTemplates backend, APP_DIRS=True, context processor "request"]   # for /api/docs
```

### 3.5 Management commands

| Command | Purpose |
|---|---|
| `migrate_schemas --shared` | Apply migrations to `public` (django-tenants) |
| `init_platform [--domain localhost]` | Create the public tenant and its domain; fill the module catalog |
| `create_platform_admin --email --password [--name]` | Create or promote a platform admin (bootstrap for the platform API) |
| `sync_modules` | Record every module found on disk, and core permissions, in the catalog |
| `provision_tenant <slug> --domain --owner-email --owner-password [--name] [--modules a,b]` | Create a tenant end to end |
| `tenant_module <slug> enable\|disable\|remove <module>` | Per-tenant module lifecycle from the CLI |
| `upgrade_modules` | After a deploy: refresh catalog, migrate schemas that have each module, record versions |
| `run_dispatcher [--once] [--interval 2]` | Deliver outbox events for every active tenant |
| `runserver` | Override: ignores module migrations in the "unapplied migrations" notice (P13) |

---

## 4. Data model

Types: `uuid` = UUID primary key (`uuid4`), `id` = `BigAutoField`. All timestamps are UTC.

### 4.1 `public` schema

**`tenancy_tenant`** (django-tenants `TenantMixin`)

| Column | Type | Notes |
|---|---|---|
| id | id | |
| schema_name | char(63), unique | `t_<slug>` with dashes turned into underscores. The platform row uses `public` |
| name | char(200) | |
| slug | slug(40), unique | The platform row uses `platform` |
| is_active | bool, default true | `false` = suspended |
| created_at | datetime | |

`auto_create_schema = True` (saving a new tenant creates and migrates its schema), `auto_drop_schema = False` (never drop customer data implicitly).

**`tenancy_domain`** (`DomainMixin`): `id`, `domain` char(253) unique, `tenant` FK (cascade, `related_name="domains"`), `is_primary` bool. Saving a primary domain demotes the others; the first domain of a tenant is primary automatically.

**`tenancy_platformauditlog`**: `id` uuid, `at` indexed, `actor_id` uuid null, `actor_email` char(254), `action` char(100) indexed, `target` char(200), `detail` JSON null.

**`users_user`** (`AbstractBaseUser`; `USERNAME_FIELD = email`)

| Column | Type | Notes |
|---|---|---|
| id | uuid | |
| email | email, unique | stored lowercase |
| name | char(200) | |
| password | char(128) | PBKDF2. Unusable password allowed (invited, not yet set) |
| last_login | datetime null | |
| is_active | bool | |
| is_platform_admin | bool | grants access to the platform API |
| created_at | datetime | |

**`users_membership`**: `id`, `user` FK (cascade), `tenant` FK (cascade, `related_name="memberships"`), `is_active`, `created_at`. Unique `(user, tenant)` named `uniq_membership`. One person may belong to many tenants.

**`catalog_module`**: `id` char(32) primary key (the module id), `name`, `version`, `manifest` JSON (the parsed manifest), `installed_at`, `updated_at`.

**`catalog_tenantmodule`**: `id`, `tenant` FK (cascade, `related_name="modules"`), `module` FK (**protect**), `status` in `enabling | enabled | disabled`, `installed_version` char(20), `enabled_at` null, `updated_at`. Unique `(tenant, module)` named `uniq_tenant_module`. **No row means the module was never enabled or its data was removed.**

**`catalog_permission`**: `code` char(100) primary key, `module` FK null (cascade; null = core permission), `description`.

### 4.2 Tenant schema (core tables)

**`iam_role`**: `id` uuid, `name` unique, `description`, `is_system` bool, `created_at`.
**`iam_rolepermission`**: `id`, `role` FK (cascade, `related_name="permissions"`), `permission` char(100). Unique `(role, permission)` named `uniq_role_permission`. Value is an exact code, a group wildcard `module.*`, or `*`.
**`iam_userrole`**: `id`, `user_id` uuid (indexed; points at `users_user` **by value**), `role` FK (cascade, `related_name="assignments"`). Unique `(user_id, role)` named `uniq_user_role`.

**`audit_auditlog`**: `id` uuid, `at` indexed, `actor_id` uuid null, `action` char(100) indexed, `entity` char(100), `entity_id` char(100), `before` JSON null, `after` JSON null.

**`events_outboxevent`**

| Column | Type | Notes |
|---|---|---|
| id | uuid | |
| name | char(120), indexed | e.g. `timesheets.entry.approved` |
| producer | char(32) | module id or `core` |
| payload | JSON | |
| version | smallint, default 1 | payload schema version |
| status | char(10), indexed | `pending`, `done`, `dead` |
| attempts | smallint | |
| next_attempt_at | datetime, default now | retry schedule |
| last_error | text | |
| parked | JSON list | module ids that were disabled when dispatched; replayed on enable |
| created_at / processed_at | datetime / null | |

**`events_inboxprocessed`**: `id`, `event_id` uuid (indexed), `handler` char(160), `processed_at`. Unique `(event_id, handler)` named `uniq_event_handler`.

### 4.3 Module tables

Created in a tenant schema by that module's migrations when the module is enabled. Prefixed with the module id. See section 8 for Timesheets.

---

## 5. Kernel

### 5.1 Manifest (`manifest.json` in the module package root)

| Field | Type | Required | Rules |
|---|---|---|---|
| `id` | string | yes | `^[a-z][a-z0-9_]{1,30}$`; not in `{core, auth, platform, admin, docs, openapi}`; **must equal the Django app label** |
| `name` | string | no | defaults to `id` |
| `version` | string | yes | `^\d+(\.\d+){0,2}$` (padded with zeros) |
| `requires` | `[{module, range}]` | no | hard dependencies; `range` defaults to `*` |
| `optional` | `[{module, range}]` | no | soft dependencies; may not repeat a `requires` entry; a module cannot depend on itself |
| `provides` | `[string]` | no | capability contract names (classes in `easybiz/core/contracts.py`). **Not yet validated against contracts** (see F17) |
| `consumes` | `[string]` | no | documentation today |
| `permissions` | `[{code, description}]` | no | every `code` must start with `<id>.` |
| `roles` | `[{name, description, permissions[]}]` | no | permissions must be a subset of the module's declared permissions |
| `events.publishes` | `[string]` | no | each must start with `<id>.` |
| `events.subscribes` | `[string]` | no | each needs a handler registered with `@subscribe` |
| `menu` | `[{label, route, permission?}]` | no | `permission` filters the menu per user |

Version ranges: exact `1.2.3`, caret `^1.2` (`>=1.2.0 <2.0.0`; `^0.2.1` means `<0.3.0`; `^0.0.3` means `<0.0.4`), tilde `~1.2.3` (`<1.3.0`), `>=1.2`, and `*`.

### 5.2 Registry (`kernel/registry.py`)

- `load_packages(packages)`: locate each package with `importlib.util.find_spec`, read `manifest.json`, reject duplicates, then call `load_order()` so a bad graph fails at startup.
- `load_order()`: every `requires` target must be installed and satisfy its range; returns a topological order, dependencies first; raises `RegistryError` on missing, incompatible or cyclic dependencies (message contains "not installed", the version found, or "cycle").
- `dependents_of(id)`: modules whose `requires` include `id`.
- `module_id_for(dotted_name)`: longest-prefix match on module packages; `easybiz.core.*` gives `"core"`.
- `add_handler(event, func)`: infers the module from `func.__module__`; a non-core handler must be listed in that module's `events.subscribes`.
- `import_module_code()`: imports `<package>.handlers` and `<package>.providers` if present, then verifies every declared subscription has a handler.
- `verify_apps()`: a Django app with label `id` must exist and its `name` must equal the package.
- `subscribe(event)`: decorator to register a handler. Handler signature: `handler(event: dict)` with keys `id, name, payload, version`.
- `kernel/apps.py::ready()` calls `ensure_loaded()`, `verify_apps()`, `import_module_code()`.

### 5.3 Discovery

`discover_module_packages(explicit)` returns the settings list plus every package that registers an entry point in group `easybiz.modules`:

```toml
[project.entry-points."easybiz.modules"]
payroll = "easybiz.modules.payroll"
```

### 5.4 State helpers (`kernel/state.py`)

`enabled_module_ids(tenant)` and `is_enabled(tenant, module_id)` read `catalog_tenantmodule` where `status = enabled`. Both accept a real `Tenant` **or the stub** installed by `schema_context()` (no pk): they resolve the real row from `schema_name` (invariant I13). The public schema resolves to "nothing enabled".

### 5.5 Module-aware migrations (the critical mechanism)

django-tenants migrates every `TENANT_APP` into **every** tenant schema. We need module tables only where the module is enabled. Two cooperating hooks implement invariant I4:

**Router `kernel/routers.py::ModuleAwareTenantSyncRouter`** (subclass of `TenantSyncRouter`, registered as both `TENANT_SYNC_ROUTER` and in `DATABASE_ROUTERS`). In `allow_migrate`, after the parent decision: for a module app, return `False` in the public schema; in a tenant schema return `module_has_tables(connection, schema, app_label)`, i.e.

```sql
SELECT 1 FROM "public".catalog_tenantmodule tm
JOIN "public".tenancy_tenant t ON t.id = tm.tenant_id
WHERE t.schema_name = %s AND tm.module_id = %s LIMIT 1
```

(any status counts, so disabled modules still receive upgrades).

**Migrate command `kernel/migrate.py::Command`** (setting `TENANT_BASE_MIGRATE_COMMAND`), a subclass of Django's `migrate`. Django still *records* a migration as applied even when the router skipped its operations, which would make a later "enable" do nothing. So for the current schema it overrides `MIGRATION_MODULES` with `{module_id: None}` for every module the schema lacks (all modules in `public`), via `override_settings`, then runs the normal `migrate`. The hidden app then has no migrations in that schema and nothing is recorded.

Resulting behaviour (all covered by tests):

| Action | Effect |
|---|---|
| `provision_tenant` | Only core tenant apps are migrated; no module tables |
| enable module for tenant X | Create the `TenantModule` row (`enabling`), run `migrate_schemas <module> --schema X`; only X gets tables |
| deploy-time `migrate_schemas` (all) | Upgrades only schemas that have the module |
| remove module data | `migrate_schemas <module> zero --schema X` (row still exists, so it is allowed), then delete the row |

### 5.6 Module lifecycle (`kernel/lifecycle.py`)

**States per tenant:** *(no row)* → `enabling` → `enabled` ⇄ `disabled` → *(no row)* after data removal.

- `install_module(id)`: in one transaction, upsert `catalog_module` (name, version, manifest JSON); upsert each declared permission; delete permissions of that module no longer declared. Idempotent; also used for upgrades.
- `sync_catalog()`: upsert core permissions (`module = null`), then `install_module` for every module in dependency order. Returns the order.
- `enable_module(tenant, id, actor_id=None)`:
  1. Module must be in the catalog and not already `enabled`.
  2. Every `requires` dependency must be `enabled` for the tenant and satisfy its version range.
  3. Inside `_keep_connection_tenant()` (invariant I12): `get_or_create` the `TenantModule` row as `enabling`.
  4. Run `migrate_schemas <id> --schema <tenant schema>`. On failure: delete the row if it was just created, otherwise set `disabled`; raise `LifecycleError("migrations for ... failed")`.
  5. In the tenant schema, in one transaction: seed the module's default roles (never overwrite existing roles), `requeue_parked(id)`, write audit `module.enabled` (with version and replayed event count), publish `core.module.enabled`.
  6. Set `status = enabled`, `installed_version`, `enabled_at`.
- `disable_module(tenant, id, actor_id)`: must be `enabled`; refuse if any enabled module `requires` it (error lists them); set `disabled`; audit `module.disabled`; publish `core.module.disabled`. Data and tables remain.
- `remove_module_data(tenant, id, actor_id, policy="drop")`: only `policy="drop"`; module must be `disabled`; refuse if a dependent module still has a row for the tenant; run `migrate_schemas <id> zero`; delete the row; strip the module's permission codes from all roles; audit `module.data_removed`.
- `upgrade_modules()`: `sync_catalog()`, then `migrate_schemas` for all schemas (the router limits it), then set `installed_version` on every `TenantModule` row to the code version.
- All lifecycle errors raise `LifecycleError`; the APIs map them to HTTP 409.

### 5.7 Middleware (`kernel/middleware.py`)

- `ModuleGateMiddleware`: regex `^/api/([a-z][a-z0-9_]*)/`. If the captured segment is an installed module and `is_enabled(request.tenant, segment)` is false, return 404 `{"detail": "Module '<id>' is not enabled for this tenant"}`.
- `TenantStatusMiddleware`: `request.tenant.is_active is False` gives 403 `{"detail": "This tenant is suspended"}`.

### 5.8 Capabilities (`kernel/capabilities.py`, `contracts.py`)

- Contracts are `typing.Protocol` classes (`@runtime_checkable`) in `easybiz/core/contracts.py`. Today: `AttendanceProvider.approved_hours(user_id, start, end) -> Decimal`.
- A module registers an implementation at import time of its `providers.py`: `capabilities.register(contract, impl, module_id)`.
- `capabilities.get(contract, optional=False)` returns the implementation only if the provider's module is enabled for `connection.tenant`; otherwise returns `None` when `optional=True`, else raises `CapabilityUnavailable`.

### 5.9 Events (`events/service.py`)

- `publish(name, payload, producer="core", version=1)`: creates an `OutboxEvent` in the **current schema and transaction**. If `producer != "core"`, the name must be in that module's `events.publishes` (else `EventError`).
- `dispatch_pending(limit=100, now=None)` runs in a tenant schema: inside one transaction, `select_for_update(skip_locked=True)` the due pending events ordered by `created_at`. For each event and each registered handler:
  - skip if `(event_id, handler.key)` is already in the inbox (`handler.key = "<module_id>.<function name>"`);
  - if the handler's module is not `core` and not enabled: add the module to `event.parked`, skip;
  - else run the handler in a savepoint and insert the inbox row; on exception record `last_error`, mark the event failed.
  - After all handlers: if any failed, `attempts += 1`; at `EASYBIZ_EVENT_MAX_ATTEMPTS` set `status = dead`, else `next_attempt_at = now + min(5 * 2**attempts, 3600) seconds`. If none failed, `status = done`.
  - Returns a Counter with keys `delivered`, `parked`, `retry`, `dead`, `events_done`.
- `requeue_parked(module_id)`: for events whose `parked` contains the module, remove it, set `pending`, `next_attempt_at = now` (the inbox prevents re-running handlers that already ran).
- `run_dispatcher` command loops over active tenants (excluding `public`; suspended tenants are paused) inside `schema_context` and calls `dispatch_pending`.

---

## 6. Platform services

### 6.1 Tenancy and provisioning

`provision_tenant(name, slug, domain, owner_email, owner_password=None, modules=(), actor_id=None)`:

1. **Validate** (`kernel/tenants.py::validate_new_tenant`), creating nothing on failure: slug matches `^[a-z][a-z0-9-]{1,30}$` and is not reserved (`public, platform, admin, api, www`); slug and schema name unused (409); domain is a valid host name (no scheme, port or path), lowercased, unused (409); owner password present (and at least 10 characters) unless the owner already has an account (422); every requested module is in the catalog, and its `requires` are in the same request (422).
2. Create the `Tenant` (schema created and core apps migrated), then the primary `Domain`, the owner user (global) and `Membership`.
3. In the tenant schema: ensure the `owner` role (`*`), assign it to the owner, audit `tenant.provisioned`.
4. Enable modules in dependency order.
5. **On any exception:** reset to public, `DROP SCHEMA IF EXISTS ... CASCADE`, delete the tenant row (cascading domains, memberships, module state), re-raise (invariant I14).

Other tenant operations (`kernel/tenants.py`): `suspend` / `resume` (409 if already in that state), `add_domain` (normalised; 409 on duplicate), `remove_domain` (a tenant keeps at least one; removing the primary promotes another), `delete_tenant(tenant, confirm_slug)` (tenant must be suspended; `confirm_slug` must equal the slug; drops the schema; people are kept).

### 6.2 Identity and authentication

- **Users are global** (`users_user`); access to a tenant is a **membership**. Roles are per tenant.
- **Password rule:** at least 10 characters when creating an account (`WeakPassword` gives 422). Hashing: PBKDF2 through `django.contrib.auth.hashers` (the auth app itself is not installed).
- **Tenant login** `POST /api/auth/login`: valid credentials **and** an active membership of the host's tenant; otherwise 401 `Invalid credentials` (the same message for every failure).
- **Tenant token** (HS256, `SECRET_KEY`): claims `sub` (user id), `tenant` (schema name), `iat`, `exp`. Validated by `TenantJWTAuth`: signature, expiry, `tenant == request.tenant.schema_name`, user active, membership active, then the endpoint permission (403 `Missing permission <code>`). Always returns 401 on the public host.
- **Platform token**: claims `sub`, `scope = "platform"`, `iat`, `exp`. Validated by `PlatformJWTAuth`: only on the public host, scope must be `platform`, and the user must be currently `is_active` and `is_platform_admin` (read from the database on every request, so demotion is immediate).
- **Platform login** `POST /api/platform/auth/login` is throttled per client IP (`EASYBIZ_PLATFORM_LOGIN_RATE`, 429 when exceeded).

### 6.3 Authorization

- A user's permissions are the union of the permissions of their roles in the tenant schema. A check passes if the set contains `*`, the exact code, or a group wildcard `module.*` that prefixes the code.
- **Assignable permissions** for a tenant = core permissions plus those of modules **enabled** for it. `create_role` rejects unknown or disabled permissions and rejects `*` (reserved for the system `owner` role); role names are unique.
- Module default roles (from the manifest) are created on enable, **never overwritten** if the tenant already has a role of that name; on data removal the module's permission codes are stripped from all roles.
- Endpoints declare permission with `auth=perm("<code>")`; `auth=authenticated` means any signed-in member.
- The menu returned by `/api/auth/me` is built from the manifests of enabled modules, filtered by each item's `permission`.

### 6.4 Audit

- **Tenant audit** (`audit_auditlog`): written via `audit.service.record(actor_id, action, entity, entity_id, before, after)` inside the caller's transaction. Actions today: `tenant.provisioned`, `module.enabled`, `module.disabled`, `module.data_removed`, `role.created`, `user.added`, `user.removed`, `timesheets.project.created`, `timesheets.entry.approved`, `timesheets.entry.rejected`.
- **Platform audit** (`tenancy_platformauditlog`) via `record_platform(actor, action, target, detail)`. Actions: `tenant.created`, `tenant.renamed`, `tenant.suspended`, `tenant.resumed`, `tenant.deleted`, `tenant.domain_added`, `tenant.domain_removed`, `tenant.module_enabled`, `tenant.module_disabled`, `tenant.module_data_removed`, `modules.synced`, `modules.upgraded`, `admin.added`, `admin.removed`.

### 6.5 CORS

`CorsMiddleware` is first. Credentials are not enabled (Bearer tokens). `CORS_ALLOWED_ORIGINS` comes from `EASYBIZ_CORS_ORIGINS`; when `DEBUG`, regexes also allow any frontend on `localhost`, `*.localhost` and `127.0.0.1` (any port). Preflights are answered before tenant resolution; 401/404 responses carry CORS headers too.

### 6.6 API documentation

Ninja serves Swagger UI. It requires: a `DjangoTemplates` backend with `APP_DIRS`, `ninja` and `django.contrib.staticfiles` in `INSTALLED_APPS`, and `STATIC_URL`. Tenant docs: `http://<tenant host>/api/docs`. Platform docs: `http://localhost:8000/api/platform/docs`. The two `NinjaAPI` instances use distinct `urls_namespace` values (`easybiz`, `platform_api`).

---

## 7. HTTP API reference

Errors are `{"detail": "..."}` unless noted. "perm" is the required permission.

### 7.1 Tenant API (tenant host, prefix `/api`)

| Method and path | Auth / perm | Request | Success | Errors |
|---|---|---|---|---|
| `POST /auth/login` | none | `{email, password}` | 200 `{access_token, token_type, expires_in}` | 401 |
| `GET /auth/me` | any member | | 200 `{id, email, permissions[], enabled_modules[], menu[{module,label,route}]}` | 401 |
| `GET /core/modules` | `core.module.read` | | 200 `[{id,name,version,status,requires[],optional[],blocked_by[]}]` where `status` is `enabled`, `disabled` or `available` | 401, 403 |
| `POST /core/modules/{id}/enable` | `core.module.manage` | | 200 module object | 409 lifecycle error |
| `POST /core/modules/{id}/disable` | `core.module.manage` | | 200 module object | 409 |
| `DELETE /core/modules/{id}/data?confirm=true` | `core.module.manage` | | 200 module object | 400 without `confirm`; 409 (not disabled, dependents) |
| `GET /core/roles` | `core.role.read` | | 200 `[{id,name,description,is_system,permissions[]}]` | |
| `POST /core/roles` | `core.role.manage` | `{name, description?, permissions[]}` | 201 role | 422 unknown or disabled permission, `*`, duplicate name |
| `GET /core/users` | `core.user.read` | | 200 `[{id,email,roles[]}]` | |
| `POST /core/users` | `core.user.manage` | `{email, password?, name?, roles[]}` | 201 user | 422 weak password, unknown role, new account without password |
| `DELETE /core/users/{id}` | `core.user.manage` | | 204; publishes `core.membership.removed` | 404, 409 (self) |
| `GET /core/audit?limit=` | `core.audit.read` | | 200 `[{at, actor_id, action, entity, entity_id}]` (limit max 200) | |

`blocked_by` on a module object lists why it cannot be enabled (missing hard dependencies) or disabled (enabled dependents).

### 7.2 Platform API (platform host, prefix `/api/platform`, all require a platform token except login)

| Method and path | Request | Success | Errors |
|---|---|---|---|
| `POST /auth/login` | `{email, password}` | 200 `{access_token, token_type, expires_in}` | 401, 429 |
| `GET /me` | | 200 `{id, email}` | 401 |
| `GET /overview` | | 200 `{tenants_total, tenants_active, tenants_suspended, platform_admins, modules_installed}` | |
| `GET /tenants?q=&is_active=&limit=&offset=` | | 200 `{count, items[Tenant]}`; the platform tenant is excluded; `limit` max 200 | |
| `POST /tenants` | `{name, slug, domain, owner_email, owner_password?, modules[]}` | 201 Tenant | 409 slug or domain exists; 422 validation, unknown module, weak or missing password |
| `GET /tenants/{slug}` | | 200 Tenant | 404 |
| `PATCH /tenants/{slug}` | `{name}` | 200 Tenant | 404 |
| `POST /tenants/{slug}/suspend` / `resume` | | 200 Tenant | 409 already in state |
| `DELETE /tenants/{slug}?confirm_slug=` | | 204 | 409 not suspended; 422 wrong or missing confirmation |
| `POST /tenants/{slug}/domains` | `{domain, is_primary?}` | 201 Tenant | 409 duplicate; 422 invalid |
| `DELETE /tenants/{slug}/domains/{domain}` | | 200 Tenant | 409 last domain; 422 not a domain of the tenant |
| `POST /tenants/{slug}/modules/{id}/enable` / `disable` | | 200 Tenant | 409 lifecycle error |
| `DELETE /tenants/{slug}/modules/{id}/data?confirm=true` | | 200 Tenant | 400 no confirm; 409 |
| `GET /modules`, `GET /modules/{id}` | | 200 Module catalog entry (below) | 404 |
| `POST /modules/sync` | | 200 `{modules[]}` (catalog refresh only) | |
| `POST /modules/upgrade` | | 200 `{modules[]}` (catalog plus migrate tenant schemas; synchronous) | |
| `GET /admins` / `POST /admins` | `{email, password?, name?}` | 200 list / 201 admin | 422 (no password for new account, weak) |
| `DELETE /admins/{id}` | | 204 | 404; 409 self or last admin |
| `GET /audit?action=&target=&limit=` | | 200 `[{at, actor_email, action, target, detail}]` | |

**Tenant object:** `{slug, name, schema_name, is_active, created_at, domains[{domain,is_primary}], modules[{module,status,installed_version}], member_count}`.
**Module catalog entry:** `{id, name, code_version, catalog_version, state, requires[], optional[], provides[], publishes[], subscribes[], permissions[{code,description}], tenants_enabled, tenants_disabled}` with `state` in `installed | not_installed | upgrade_pending | missing_code`.
**Route order rule:** fixed paths (`/modules/sync`, `/modules/upgrade`) must be registered before parameterised ones (`/modules/{id}`), otherwise the parameterised pattern swallows them (P8).

---

## 8. Reference module: Timesheets

Purpose: prove the module contract end to end (models, API, permissions, events, handlers, capability, menu, default roles). Package `easybiz/modules/timesheets`, app label `timesheets`, version `0.1.0`, no dependencies.

### 8.1 Tables (tenant schema, only when enabled)

**`timesheets_project`**: `id` uuid, `code` char(30) unique (stored uppercase), `name` char(200), `is_active` bool, `created_at`.
**`timesheets_entry`**: `id` uuid, `user_id` uuid indexed (by value), `project` FK (protect), `work_date` date indexed, `hours` decimal(4,2), `note` char(300), `status` char(10) indexed in `draft | submitted | approved | rejected`, `reviewed_by` uuid null, `review_note` char(300), `created_at`. Check constraint `timesheets_hours_range`: `0 < hours <= 24` (use `condition=` in Django 6).

### 8.2 Permissions and default roles

`timesheets.project.read`, `timesheets.project.manage`, `timesheets.entry.create`, `timesheets.entry.read`, `timesheets.entry.approve`.
Roles: `timesheet_user` (project.read, entry.create, entry.read); `timesheet_approver` (all five).
Menu: "Timesheets" (`/timesheets`, needs `entry.read`), "Projects" (`/timesheets/projects`, needs `project.manage`).

### 8.3 API (prefix `/api/timesheets`)

| Endpoint | perm | Rules |
|---|---|---|
| `GET /projects` | `project.read` | ordered by code |
| `POST /projects` `{code, name}` | `project.manage` | code uppercased; duplicate gives 409; audit `timesheets.project.created` |
| `GET /entries?status=&user_id=` | `entry.read` | users see only their own; holders of `entry.approve` see all and may filter by `user_id` |
| `POST /entries` `{project_id, work_date, hours, note?}` | `entry.create` | project must exist and be active (404); `hours` in (0, 24] (422); creates a `draft` for the caller |
| `POST /entries/{id}/submit` | `entry.create` | own entry only (404 otherwise); `draft` or `rejected` becomes `submitted` (409 otherwise) |
| `POST /entries/{id}/approve` | `entry.approve` | entry must be `submitted` (409); **cannot review own time** (403); sets `approved`, writes audit and publishes `timesheets.entry.approved` in one transaction |
| `POST /entries/{id}/reject` `{reason?}` | `entry.approve` | same rules; sets `rejected`; publishes `timesheets.entry.rejected` |

### 8.4 Events, handler and capability

- Publishes `timesheets.entry.approved` and `timesheets.entry.rejected`, payload `{entry_id, user_id, project_id, work_date, hours}` (hours as string).
- Subscribes to `core.membership.removed` (`handlers.py::drop_draft_entries`): deletes that user's `draft` entries; submitted and approved time is kept.
- Provides `AttendanceProvider` (`providers.py`): `approved_hours(user_id, start, end)` sums approved hours in the date range (drafts, submitted and rejected do not count).

---

## 9. Testing infrastructure

- Runner: `pytest`, run via `uv run pytest`, with `pytest.ini`: `testpaths = tests easybiz`, `addopts = -q -p no:django` (pytest-django must be off; it blocks database access). Global fixtures in the top-level `tests/conftest.py`; module fixtures in `easybiz/modules/<id>/conftest.py` (§0.5).
- Database: `settings.py` picks `easybiz_test` when `pytest` is loaded. A session-scoped autouse fixture (`platform`) **drops and recreates** that database, runs `migrate_schemas --shared`, then `init_platform`. Tests commit real data; isolation comes from unique slugs per tenant.
- `conftest.py` provides: `Tenant` helper (host, `login()`, `token()`, `get/post/delete(..., as_user=)`, `add_user()`); `make_tenant(modules=())`; fixtures `acme` and `zenith` (session-scoped, Timesheets enabled), `fresh` (new tenant, no modules), `fresh_ts` (new tenant with Timesheets); `Platform` helper and `admin` fixture for the platform API; `tables_in(schema)`; an autouse fixture that resets the connection to the public schema before and after each test.
- Use `tenant_context(tenant)` (not bare `schema_context`) when a test needs the real tenant.
- To exercise failure paths, tests append a `Handler` to `registry._handlers[...]` (and remove it in `finally`) or monkeypatch `provisioning.enable_module`.

## 10. Test catalogue (acceptance for Part A)

All 85 tests must pass. Grouped by file:

**`test_manifest_and_registry.py`** (no DB, 26 tests): version-range truth table; invalid manifests rejected (bad id, reserved id, bad version, wrong permission prefix, wrong event prefix, role with undeclared permission, self dependency, duplicate dependency, missing id); load order puts dependencies first; missing hard dependency fails fast; incompatible dependency version fails; dependency cycle detected (ids need two or more characters); `dependents_of`.

**`test_tenancy_and_auth.py`** (9): each tenant has its own schema with core tables, identity tables only in `public`; data isolation between two tenants (API and ORM); login and `/me`; bad credentials and missing or garbage tokens give 401; owner of one tenant cannot log in to another; token for one tenant refused by another; permission enforcement (403); one person in two tenants with different rights; platform host does not serve the tenant API but serves `/health`.

**`test_module_lifecycle.py`** (11): no routes or tables before enable; enable creates tables only in that tenant; enable seeds roles and audits; module listing shows status; enable twice and unknown module give 409; permissions of disabled modules cannot be assigned; disable hides module but keeps data, re-enable restores it; removing data needs disable and `confirm`; remove data drops tables and a clean re-enable recreates them; deploy-time `migrate_schemas` touches only schemas that have the module; `upgrade_modules` refreshes versions.

**`test_timesheets_and_events.py`** (11): full submit and approve flow with rules (no approval without permission, no self-approval, no double approval); visibility (own versus all); validation (hours bounds, unknown project, duplicate code case-insensitive); menu follows permissions; approval publishes an outbox event in the same transaction; a module cannot publish an undeclared event; removed user's drafts are cleaned up via an event (approved time kept); handlers are idempotent (inbox); events for a disabled module are parked then replayed on enable; failing handler retries with backoff then dead-letters; capability provided only while enabled (sum of approved hours; `None` or `CapabilityUnavailable` otherwise).

**`test_cors.py`** (4): preflight answered for a tenant host with correct headers; preflight needs neither the module nor a token; error responses carry CORS headers; subdomain frontends allowed, unknown origins not.

**`test_platform_api.py`** (24): login and `/me`; bad credentials and missing token; tenant owner is not a platform admin; tokens not interchangeable; platform API absent on tenant hosts; login rate limited (429); demoted admin loses access immediately; create tenant with module end to end; validation and conflicts (409 slug and domain, 422 bad slug, reserved slug, bad domain, missing and weak password); unknown module creates nothing; existing person can own another tenant without a password; failure midway rolls everything back (no tenant row, schema or domain left); list, detail, search and hidden platform tenant; overview counts; rename; suspend blocks login, API with an old token, and docs, then resume restores; delete requires suspension and confirmation then drops the schema (people kept); domains (normalisation, primary switching, host serves tenant, duplicate and last-domain protection); module lifecycle from the platform; module catalog and counts; sync and upgrade; admin management guards; promoting an existing user; platform actions audited in order.

---

## 11. Build milestones for Part A (rebuild order)

Each milestone ends with a verification the agent must run. Dev database: `docker compose up -d db`.

**M0. Skeleton.** Repo layout, `requirements*.txt`, `docker-compose.yml`, `pytest.ini`, `settings.py` per section 3 (apps, middleware, router settings, templates, static, CORS), empty app packages, `urls*.py`.
*Verify:* `python manage.py check` reports no issues.

**M1. Tenancy and identity.** Models `Tenant`, `Domain`, `User`, `Membership` with `makemigrations`; `init_platform` (public tenant and domain, then catalog sync).
*Verify:* `migrate_schemas --shared` then `init_platform` succeed; `/health` on `localhost` returns `{"status":"ok","scope":"platform"}`.

**M2. Kernel core.** `manifest.py`, `registry.py`, `discovery.py`, `state.py`, `capabilities.py`, `contracts.py`, `kernel/apps.py`.
*Verify:* `tests/test_manifest_and_registry.py` passes (26 tests).

**M3. Catalog, module-aware migrations, lifecycle, provisioning.** Models `Module`, `TenantModule`, `Permission`; tenant apps `iam`, `audit`, `events` (models only); `routers.py`, `migrate.py`; `lifecycle.py`; `provisioning.py`; commands `sync_modules`, `provision_tenant`, `tenant_module`, `upgrade_modules`; a minimal module so there is something to enable.
*Verify (manual):* provision two tenants, enable the module for one: its tables exist in exactly that schema and nowhere else, not in `public`, and `django_migrations` of the other schema has no row for the module.

**M4. AuthN, AuthZ, audit, tenant API.** `users/service.py`, `iam/service.py`, `audit/service.py`, `api/auth.py`, `api/core_routes.py`, both middlewares, docs and static setup.
*Verify:* login and `/me` work; `/api/docs` renders with CSS and JS; module gate returns 404 before enable and 200 after.

**M5. Events.** `events/service.py`, `run_dispatcher`.
*Verify:* event tests in `test_timesheets_and_events.py` pass.

**M6. Timesheets module.** Section 8 in full, with migrations.
*Verify:* `test_timesheets_and_events.py` and `test_module_lifecycle.py` pass.

**M7. Platform API.** `tenancy` audit model and migration, `tenants.py`, hardened `provisioning.py`, `platform_api/*`, `urls_public.py`, `create_platform_admin`, tenant status middleware, dispatcher skips suspended tenants.
*Verify:* `test_platform_api.py` passes (24).

**M8. CORS, runserver override, README.** `corsheaders`, `runserver` override, README sections.
*Verify:* `test_cors.py` passes; `runserver` shows no "unapplied migration" notice for module apps.

**M9. Full verification.** `pytest` (85 passed), `python manage.py check`, `makemigrations --check --dry-run`, a manual run: create platform admin, create a tenant over HTTP, log in as its owner, enable a module, suspend and delete.

---

## 12. Decisions and pitfalls log

### 12.1 Decisions

| # | Decision | Why |
|---|---|---|
| D1 | Schema-per-tenant, no row-level security | Hard isolation without a `tenant_id` filter to forget; per-tenant backup, restore and offboarding; different module sets per tenant. Cost: migrations fan out per schema |
| D2 | Django plus Django Ninja (not FastAPI) | ORM, migrations and mature tenancy tooling; Ninja gives typed, OpenAPI-first endpoints |
| D3 | Users and memberships in `public`; roles in tenant schema | One login across tenants and SSO later; authorization stays tenant-local |
| D4 | Module tables created when the module is enabled | Clean per-tenant data and removal. Fallback if it proves fragile: create every installed module's tables in every schema and treat "enabled" as a flag |
| D5 | Outbox and inbox in the tenant schema | Atomic with business data; replayable per tenant; tenant export includes its events |
| D6 | All installed modules mounted; gate by middleware | Routes cannot be added at runtime in Django; the gate gives per-tenant behaviour without reloads |
| D7 | Capability interfaces plus events, never imports | Keeps modules independent and swappable |
| D8 | At-least-once delivery with idempotent handlers | Simple and robust; exactly-once is not required |
| D9 | New module **code** needs a restart or rolling deploy; enable/disable is instant | `INSTALLED_APPS` is fixed at startup |
| D10 | HS256 JWT in the MVP | Simplest; rotation and RS256 are F13 |
| D11 | Polling dispatcher in the MVP | Simplest; Celery is F15 |
| D12 | Platform admin is a flag on the global user | Simplest; finer platform roles are F16 |

### 12.2 Pitfalls found while building (do not repeat)

| # | Pitfall | Fix |
|---|---|---|
| **P1** | Management commands from earlier apps in `INSTALLED_APPS` win. django-tenants already has `create_tenant`; `staticfiles` has `runserver` | Name commands uniquely (`provision_tenant`); list `easybiz.core.kernel` right after `django_tenants` so its `runserver` override wins |
| **P2** | Django records a migration as applied even if the router skipped its operations, so a later enable would do nothing | The per-schema migrate hook (section 5.5) |
| **P3** | django-tenants' system check requires its router; a subclass in `DATABASE_ROUTERS` alone fails | Set `TENANT_SYNC_ROUTER` to the subclass and also list it in `DATABASE_ROUTERS` |
| **P4** | django-tenants requires `django.contrib.contenttypes` installed | Install it in shared apps |
| **P5** | `migrate_schemas` resets the connection to `public` | Wrap calls in `_keep_connection_tenant()` and restore afterwards (I12) |
| **P6** | `schema_context()` installs a stub tenant with no pk, so `is_enabled(connection.tenant, ...)` returned false and every event got parked | Resolve the real tenant from `schema_name` (I13) |
| **P7** | `/api/docs` failed with "No DjangoTemplates backend is configured", then rendered blank | Add `TEMPLATES`, `ninja` and `staticfiles` apps, `STATIC_URL` |
| **P8** | `GET /modules/{id}` registered before `POST /modules/sync` swallowed it (405) | Register fixed paths before parameterised ones |
| **P9** | Ninja `AuthorizationError` produced an invalid status code; returning `(status, body)` tuples is deprecated | Raise `HttpError(403, ...)`; return `Status(code, body)` |
| **P10** | A custom user model without `django.contrib.auth` installed | Use `AbstractBaseUser` and `auth.hashers` directly; no Django admin |
| **P11** | pytest-django blocks DB access and conflicts with the real-database fixture | `-p no:django`; manage the DB in `conftest.py` |
| **P12** | Django 6 removed `CheckConstraint(check=...)` | Use `condition=` |
| **P13** | `runserver` always warned "1 unapplied migration" because it checks only `public`, where module migrations never apply | `runserver` override that ignores module apps and still warns for real shared migrations |
| **P14** | Swagger's "Failed to fetch ... CORS" is a generic message. Same-origin docs never need CORS; the real cause was a down or crashed server | Check the server console and the browser Network tab first |
| **P15** | `Tenant.delete(force_drop=True)` fails if the schema does not exist | Drop with `DROP SCHEMA IF EXISTS ... CASCADE`, then delete the row |
| **P16** | Validating after creating the schema leaves orphan schemas | Validate everything first; roll back fully on failure (I14) |
| **P17** | Short JWT secrets trigger warnings and are insecure | Default is 32+ characters; require a real secret in production |
| **P18** | `*.localhost` hosts must be allowed and tenant APIs are not reachable on the platform host | `ALLOWED_HOSTS` includes `.localhost`; use the tenant's own domain |

---

# PART B: Remaining features

## 13. Roadmap and feature template

### 13.1 Feature index

Feature ids are stable (`F1` to `F22`). "Depends" lists features that must exist first. Priority: **P1** proves the architecture, **P2** completes the platform, **P3** hardens and scales.

| ID | Feature | Priority | Depends | Section |
|---|---|---|---|---|
| F1 | HR module (`EmployeeProvider`, soft link from Timesheets) | P1 | | 14 |
| F2 | Payroll module (hard dependency on HR, optional on Timesheets) | P1 | F1 | 14 |
| F14 | Authorization v2 (role CRUD, ABAC, org scope, caching) | P1 | | 17 |
| F17 | Module system v2 (scaffold, contract test kit, capability versioning) | P1 | | 20 |
| F7 | Numbering series | P2 | | 15 |
| F5 | Settings and feature flags | P2 | | 15 |
| F3 | Org structure | P2 | F14 | 15 |
| F4 | Master data (party, item, currency, UoM) | P2 | F7 | 15 |
| F6 | Custom fields | P2 | | 15 |
| F11 | Jobs and scheduler | P2 | F15 | 15 |
| F8 | Workflow and approvals | P2 | F14, F11 | 15 |
| F9 | Notifications and webhooks | P2 | F11 | 15 |
| F10 | Files | P2 | | 15 |
| F12 | i18n and localisation | P2 | | 15 |
| F15 | Events v2 (Celery, dead-letter API, schemas, retention) | P2 | | 18 |
| F13 | Authentication hardening (refresh, reset, MFA, SSO, API keys, key rotation) | P2 | | 16 |
| F21 | API conventions (pagination, errors, idempotency, concurrency) | P2 | | 22 |
| F16 | Platform v2 (async provisioning, plans, roles, impersonation, export, sharding) | P3 | F11, F15 | 19 |
| F18 | Frontend (React shell and admin UIs) | P3 | F21, F14 | 21 |
| F19 | Observability and operations | P3 | | 22 |
| F20 | Security and compliance | P3 | F13 | 22 |
| F22 | Performance and scale | P3 | F15 | 22 |

**Suggested order:** F14, F17, F1, F2 (prove modularity), then F7, F5, F15, F11, F3, F4, F6, F8, F9, F10, F12, F13, F21, then F16, F19, F20, F22, with F18 started once F21 and F14 are done.

### 13.2 Feature template

Every feature section contains: **Purpose**; **Depends on**; **Design** (entities, rules, permissions, events); **API**; **Acceptance criteria** (checkboxes the agent must satisfy and test). A feature is done when the Definition of done (0.3) also holds.

### 13.3 Rules that apply to every new core service

- A new core service is a Django app under `easybiz/core/` listed in `TENANT_APPS` (tenant data) or `SHARED_APPS` (platform data), never both.
- Tenant-schema tables of core services are created for every tenant at provisioning. Existing tenants receive them through `migrate_schemas` (document this in the upgrade notes).
- New core permissions go in `kernel/core_permissions.py` and are synced by `sync_catalog()`.
- Core services never import modules. Modules reach core services through `easybiz.core.*` public functions only.
- References from module tables to core entities are UUID values (I2).
- Add the feature's tables, events and permissions to the appendices.

---

## 14. Additional business modules (prove modularity)

These two modules exist to **prove the architecture**: hard and soft dependencies, capability interfaces, events across modules, and independent operation. Follow section 20 (F17) for the scaffold and contract kit if already built; otherwise copy the layout of `easybiz/modules/timesheets`.

### F1. HR module (`easybiz/modules/hr`, id `hr`, version `0.1.0`)

**Purpose:** employee master and leave management; source of the `EmployeeProvider` capability.
**Depends on:** nothing (works alone). Uses core org structure (F3) later via `org_unit_id` UUID.

**Design: tables (tenant schema, prefix `hr_`)**

| Table | Key columns |
|---|---|
| `hr_position` | `id` uuid, `title`, `grade` null, `is_active` |
| `hr_employee` | `id` uuid, `employee_no` unique (manual until F7), `user_id` uuid null (core user; unique among non-terminated employees), `first_name`, `last_name`, `email`, `org_unit_id` uuid null, `position_id` FK null, `manager_id` uuid null (employee, by value), `status` in `active \| on_leave \| terminated`, `hire_date`, `termination_date` null, `created_at` |
| `hr_contract` | `id`, `employee` FK, `kind` in `permanent \| fixed_term \| contractor`, `start_date`, `end_date` null, `weekly_hours` decimal. (Pay lives in Payroll, not here) |
| `hr_leavetype` | `id`, `code` unique, `name`, `paid` bool, `requires_approval` bool |
| `hr_leaverequest` | `id`, `employee` FK, `leave_type` FK, `start_date`, `end_date`, `status` in `pending \| approved \| rejected \| cancelled`, `decided_by` uuid null, `reason` |

**Capability contract** (add to `easybiz/core/contracts.py`):

```python
@dataclass(frozen=True)
class EmployeeInfo:
    id: UUID; number: str; full_name: str; email: str | None
    user_id: UUID | None; org_unit_id: UUID | None
    status: str; hire_date: date; termination_date: date | None

@runtime_checkable
class EmployeeProvider(Protocol):
    def get(self, employee_id: UUID) -> EmployeeInfo | None: ...
    def find_by_user(self, user_id: UUID) -> EmployeeInfo | None: ...
    def list_active(self, on: date, org_unit_id: UUID | None = None) -> list[EmployeeInfo]: ...
```

**Permissions:** `hr.employee.read`, `hr.employee.manage`, `hr.contract.read`, `hr.contract.manage`, `hr.leave.request`, `hr.leave.approve`, `hr.leave.read_all`.
**Default roles:** `hr_admin` (all), `hr_manager` (employee.read, leave.approve, leave.read_all), `hr_employee` (leave.request; sees only own data).
**Events published:** `hr.employee.hired`, `hr.employee.updated`, `hr.employee.terminated` (`{employee_id, user_id, effective_date}`), `hr.leave.approved` (`{employee_id, leave_id, start_date, end_date, leave_type}`).
**Subscribes:** `core.membership.removed` (clears `user_id` on the linked employee; does not delete the employee).
**Rules:** terminating sets `status` and `termination_date` and publishes `hr.employee.terminated` in the same transaction; terminated employees cannot receive new leave; leave periods may not overlap for one employee; an employee may not approve their own leave; a user is linked to at most one non-terminated employee; contract data requires `hr.contract.read`.
**API (`/api/hr`):** employees CRUD (`GET/POST /employees`, `GET/PATCH /employees/{id}`, `POST /employees/{id}/terminate`), positions CRUD, contracts per employee, leave types CRUD, `POST /leave`, `POST /leave/{id}/approve|reject|cancel`, `GET /leave?employee_id=&status=`, `GET /me` (the caller's own employee record).

**Timesheets integration (soft dependency).** Update `timesheets/manifest.json`: `"optional": [{"module": "hr", "range": "^0.1"}]`, `"consumes": ["EmployeeProvider"]`, `subscribes` adds `hr.employee.terminated`. Behaviour:
- If `capabilities.get(EmployeeProvider, optional=True)` returns a provider, creating an entry requires the caller to map to an `active` employee (else 422 `"not an active employee"`).
- If HR is not enabled, Timesheets behaves exactly as before.
- Handler `hr.employee.terminated`: delete that user's draft entries dated after the effective date.

**Acceptance criteria**
- [ ] HR enables and works alone; Timesheets still passes all existing tests without HR.
- [ ] With both enabled, Timesheets rejects entries from non-employees and terminated employees; with HR disabled it accepts them again.
- [ ] `capabilities.get(EmployeeProvider)` works only while HR is enabled for the tenant; `optional=True` returns `None` otherwise.
- [ ] Terminating an employee publishes the event in the same transaction; the Timesheets handler runs through the dispatcher and is idempotent.
- [ ] Events published while Timesheets is disabled are parked and replayed on enable (existing mechanism).
- [ ] Contract data is hidden without `hr.contract.read`; employees see only their own leave unless they hold `hr.leave.read_all`.
- [ ] Isolation test: employees of tenant A are invisible to tenant B.
- [ ] Table prefix `hr_`, no foreign keys to other modules' tables, manifest validates, migrations generated.

### F2. Payroll module (`easybiz/modules/payroll`, id `payroll`, version `0.1.0`)

**Purpose:** compute and approve pay runs from employee data and, when available, approved attendance.
**Depends on:** `hr` (hard, `^0.1`); `timesheets` (optional, `^0.1`).

**Design: tables (prefix `payroll_`)**

| Table | Key columns |
|---|---|
| `payroll_paycomponent` | `id`, `code` unique, `name`, `kind` in `earning \| deduction \| employer_contribution`, `calc` in `fixed \| percent_of_gross \| hourly`, `value` decimal, `taxable` bool, `is_active` |
| `payroll_compensation` | `id`, `employee_id` uuid (by value), `effective_from`, `effective_to` null, `base_amount` decimal, `currency` char(3), `basis` in `monthly \| hourly`. No overlapping ranges per employee |
| `payroll_run` | `id`, `number` (series F7; manual until then), `period_start`, `period_end`, `status` in `draft \| calculated \| approved \| paid \| cancelled`, `approved_by` null, `approved_at` null, `created_by`, `created_at` |
| `payroll_payslip` | `id`, `run` FK, `employee_id` uuid, `gross`, `deductions`, `net`, `currency`, `status` in `draft \| issued` |
| `payroll_payslipline` | `id`, `payslip` FK, `component_code`, `kind`, `quantity`, `basis`, `amount` |

**Calculation rules**
- Employees come from `EmployeeProvider.list_active(period_end)`; an employee without a valid compensation for the period is reported in the run result as `skipped` with a reason (never silently dropped).
- Monthly basis: full amount, prorated by calendar days for hires or terminations inside the period. Hourly basis: hours from `AttendanceProvider.approved_hours` when Timesheets is enabled; otherwise from a manual hours entry endpoint (`POST /runs/{id}/hours`); if neither exists the employee is `skipped`.
- Money uses `Decimal`; rounding is half-up to the currency's minor units (use core master data F4 `Currency.minor_units` when available, else 2).
- Recalculation of a `draft` or `calculated` run is deterministic and idempotent (delete and recreate payslips in one transaction). An `approved` or `paid` run is **immutable**; corrections are made by a new run.

**Permissions:** `payroll.component.manage`, `payroll.compensation.read`, `payroll.compensation.manage`, `payroll.run.read`, `payroll.run.create`, `payroll.run.approve`, `payroll.payslip.read` (own payslips need only authentication plus a linked employee; all payslips need this permission).
**Rules:** the approver may not be the run's creator; every read of compensation or payslips by someone other than the subject writes an audit row (sensitive-data access, see F20).
**Events published:** `payroll.run.approved`, `payroll.run.paid`, `payroll.payslip.issued`. **Subscribes:** `hr.employee.terminated` (flags the employee for a final-pay review on the next run).
**API (`/api/payroll`):** components CRUD, compensation CRUD per employee, runs (`POST /runs`, `POST /runs/{id}/calculate`, `POST /runs/{id}/approve`, `POST /runs/{id}/mark-paid`, `GET /runs/{id}`, `GET /runs/{id}/payslips`), `GET /payslips/me`.

**Acceptance criteria**
- [ ] Payroll cannot be enabled for a tenant where HR is not enabled (409 naming `hr`); HR cannot be disabled while Payroll is enabled (409 naming `payroll`); data removal of HR is refused while Payroll holds data.
- [ ] Payroll works with Timesheets absent (manual hours path) and uses approved attendance when Timesheets is enabled; both paths tested.
- [ ] Hourly calculation matches a hand-computed fixture; monthly proration for a mid-period hire and termination matches a fixture.
- [ ] Skipped employees are listed with reasons; recalculation is idempotent; approved runs reject recalculation (409).
- [ ] Creator cannot approve; payslips of other employees need `payroll.payslip.read`; sensitive reads are audited.
- [ ] Module gate, isolation, and manifest tests pass; no cross-module foreign keys.
- [ ] A contract-kit run (F17) passes for Payroll alone-with-HR and with-and-without Timesheets.

---

## 15. Core platform services (tenant schema unless stated)

### F7. Numbering series (`easybiz.core.numbering`)

**Purpose:** consistent, gapless, human-readable document numbers (`INV-2026-00042`).
**Design:** table `numbering_series` (`id`, `key` unique like `payroll.run`, `pattern`, `scope` in `tenant | org_unit`, `org_unit_id` null, `reset` in `never | yearly | monthly`, `padding`, `next_value`, `last_reset_key`). Pattern tokens: `{seq}`, `{seq:05d}`, `{YYYY}`, `{YY}`, `{MM}`, `{org}`. Modules declare series in the manifest (`"numbering": [{"key": "payroll.run", "pattern": "PR-{YYYY}-{seq:05d}", "reset": "yearly"}]`) and the lifecycle seeds them on enable.
**API:** `numbering.next(key, org_unit_id=None, on=None) -> str` (Python only, used inside the caller's transaction); `GET /api/core/numbering`, `PATCH /api/core/numbering/{key}` (pattern changes apply to future numbers only). Permissions `core.numbering.read`, `core.numbering.manage`.
**Rules:** allocation uses `SELECT ... FOR UPDATE` on the series row inside the caller's transaction, so a rolled-back transaction releases its number (gapless); reset occurs when the period key changes; the counter never decreases.
**Acceptance**
- [ ] 20 concurrent transactions allocate 20 unique, contiguous numbers.
- [ ] A rolled-back transaction does not consume a number.
- [ ] Yearly and monthly resets work across a simulated period boundary; org-scoped series are independent.
- [ ] Manifest-declared series are seeded on enable and ignored if they already exist.
- [ ] Changing a pattern affects only subsequent numbers; audit row written.

### F5. Settings and feature flags (`easybiz.core.settings`)

**Purpose:** typed per-tenant configuration for core and modules, plus feature flags.
**Design:** tenant table `settings_setting` (`id`, `namespace`, `key`, `value` JSON, `scope` in `tenant | org_unit`, `org_unit_id` null, `updated_by`, `updated_at`; unique `(namespace, key, scope, org_unit_id)`). Modules declare a JSON Schema in the manifest (`"settings": {"schema": {...}, "defaults": {...}}`). Secret fields (marked `"x-secret": true`) are encrypted at rest (Fernet key from environment) and masked in responses. Public table `flags_feature` (`key`, `default`, `description`) plus tenant table `settings_flagoverride` (`key`, `value`); `flags.is_on(key)` resolves tenant override then default.
**API:** `GET /api/core/settings/{namespace}` (merged defaults, tenant and org-unit values), `PUT /api/core/settings/{namespace}`; `GET /api/core/flags`, `PUT /api/core/flags/{key}`. Platform API: manage flag defaults and per-tenant overrides. Permissions `core.settings.read`, `core.settings.manage`, `core.flags.manage`.
**Acceptance**
- [ ] Values are validated against the module's schema (422 with field errors); unknown namespaces 404.
- [ ] Org-unit values override tenant values; resolution order is tested.
- [ ] Secrets are encrypted in the database and masked in API output; rotating the key is documented.
- [ ] A disabled module's namespace is hidden; its values are kept.
- [ ] Flag resolution (override beats default) is tested; changes are audited.

### F3. Org structure (`easybiz.core.org`)

**Purpose:** company, branch, department and cost-centre hierarchy that every module scopes data by.
**Design:** table `org_orgunit` (`id` uuid, `parent` FK self null, `kind` in `company | branch | department | cost_center`, `code` unique, `name`, `path` text materialised as `/<id>/<id>/`, `depth`, `is_active`, `manager_user_id` null). Table `org_userscope` (`id`, `user_id` uuid, `org_unit` FK, `include_descendants` bool). Provisioning seeds one root company named after the tenant.
**Rules:** allowed parent kinds (company root; branch under company; department under company or branch; cost centre under any); no cycles; moving a unit recomputes the subtree's paths in one transaction; units are deactivated, never hard-deleted; deactivation is refused while active children exist. Helper `easybiz.core.org.scope.restrict(queryset, user_id, field="org_unit_id")` limits a queryset to the units in the user's scopes (and descendants); a user with no scope rows sees the whole tenant only if they hold `core.org.scope.all`.
**Events:** `core.org.unit.created`, `.updated`, `.moved`, `.deactivated`.
**API (`/api/core/org`):** `GET /units?kind=&parent=&q=`, `GET /tree`, `POST /units`, `PATCH /units/{id}`, `POST /units/{id}/move`, `POST /units/{id}/deactivate`, `GET/PUT /users/{user_id}/scope`. Permissions `core.org.read`, `core.org.manage`, `core.org.scope.all`.
**Acceptance**
- [ ] Hierarchy rules, cycle prevention and path recomputation on move are tested.
- [ ] `restrict()` returns exactly the allowed rows for scoped users, and everything only for `core.org.scope.all` holders.
- [ ] HR and Timesheets can use `org_unit_id` for filtering without importing `easybiz.core.org` models (only the helper).
- [ ] Deactivation publishes an event; modules' handlers react idempotently.
- [ ] Isolation and audit tests pass.

### F4. Master data (`easybiz.core.masterdata`)

**Purpose:** shared reference data: currencies, units of measure, parties and items.
**Design (tenant schema):**
- `md_currency` (`code` char(3) pk, `name`, `minor_units`), `md_exchangerate` (`from_code`, `to_code`, `rate` decimal(18,8), `valid_on`, `source`).
- `md_uom` (`code` pk, `name`, `category`), `md_uomconversion` (`from_code`, `to_code`, `factor` decimal(18,8)).
- `md_party` (`id` uuid, `number` via series `core.party`, `kind` in `person | organization`, `name`, `legal_name`, `tax_id`, `email`, `phone`, `is_active`), `md_partyrole` (`party` FK, `role` in `customer | supplier | carrier | other`), `md_address` (`party` FK, `kind`, `line1`, `line2`, `city`, `region`, `postal_code`, `country` char(2)).
- `md_item` (`id` uuid, `sku` unique case-insensitive, `name`, `description`, `kind` in `goods | service`, `uom` FK, `barcode` null, `is_active`).
**Rules:** records are deactivated, never deleted; `convert(amount, from, to, on)` uses the latest rate on or before the date and rounds to the target's `minor_units`; UoM conversion is category-checked; duplicate `tax_id` among active parties produces a warning field in the response (not an error). Tenants are seeded with ISO 4217 currencies and common UoMs.
**Events:** `core.party.changed`, `core.item.changed` (payload: id, change type).
**API (`/api/core/masterdata`):** CRUD for currencies (manage only), rates, UoMs, parties (with roles and addresses), items; `GET /convert?amount=&from=&to=&on=`. Permissions `core.party.read|manage`, `core.item.read|manage`, `core.currency.read|manage`. CSV import and export runs as a job (F11) using files (F10).
**Acceptance**
- [ ] SKU uniqueness is case-insensitive; deactivated items remain referenceable by UUID.
- [ ] Conversion handles missing-date fallback, inverse rates, and rounding; fixtures cover each case.
- [ ] Party roles and addresses CRUD, duplicate `tax_id` warning, numbering through F7.
- [ ] Change events fire in the same transaction as the change.
- [ ] Permissions and isolation tests pass.

### F6. Custom fields (`easybiz.core.customfields`)

**Purpose:** tenants add fields to module entities without code changes.
**Design:** table `cf_fielddef` (`id`, `entity` like `hr.employee`, `key` slug, `label`, `type` in `text | number | date | boolean | choice | multichoice`, `required`, `options` JSON, `validation` JSON (min, max, regex, length), `position`, `is_active`; unique `(entity, key)`). Modules opt in per entity by adding the abstract `CustomFieldsMixin` (a `custom = JSONField(default=dict)` column) and listing the entity in the manifest (`"custom_fields": ["hr.employee"]`). `customfields.validate(entity, data)` returns the cleaned dict or raises a validation error; module APIs include `custom` in read and write schemas.
**Rules:** keys are immutable; type changes are refused when data exists (deactivate and add a new field instead); inactive definitions keep their data but are hidden; required fields apply to new and updated records only. JSONB GIN index on the column; filter support `?cf.<key>=value`.
**API:** `GET/POST /api/core/custom-fields?entity=`, `PATCH /api/core/custom-fields/{id}`. Permissions `core.customfields.read|manage`.
**Acceptance**
- [ ] A custom field added through the API appears in the entity's API (read and write) and is validated by type and constraints.
- [ ] Type change with data is refused; deactivation hides but keeps values.
- [ ] Filtering by custom field works and uses the index (check with `EXPLAIN` in a test on a seeded table).
- [ ] Only entities declared in a manifest can be extended; disabled modules' definitions are hidden.

### F11. Jobs and scheduler (`easybiz.core.jobs`)

**Purpose:** run background and scheduled work per tenant, with history.
**Design:** manifests declare jobs: `"jobs": [{"name": "monthly-close", "cron": "0 2 1 * *", "handler": "easybiz.modules.payroll.jobs:monthly_close", "timeout_seconds": 600}]`. Tenant tables `jobs_job` (seeded from manifests on enable: `name`, `module`, `cron`, `enabled`, `last_run_at`, `next_run_at`) and `jobs_jobrun` (`id` uuid, `job` FK null, `kind` (`scheduled | manual | adhoc`), `status` in `queued | running | succeeded | failed | cancelled`, `started_at`, `finished_at`, `attempts`, `error`, `result` JSON). A scheduler loop (`run_scheduler`, or Celery beat after F15) enqueues due jobs for **active tenants whose module is enabled**; workers run each job inside `tenant_context`. An advisory lock per `(tenant, job)` prevents overlapping runs. Ad-hoc jobs: `jobs.enqueue(handler, args, tenant)` for long operations (imports, exports, upgrades).
**API:** `GET /api/core/jobs`, `POST /api/core/jobs/{name}/run`, `PATCH /api/core/jobs/{name}` (enable, change cron), `GET /api/core/jobs/runs?status=`, `GET /api/core/jobs/runs/{id}`. Permissions `core.jobs.read|manage`.
**Acceptance**
- [ ] A due job runs once per schedule tick, in the right tenant schema, with history recorded.
- [ ] Jobs of a disabled module and of suspended tenants do not run; they resume on enable and resume.
- [ ] Overlapping runs are prevented (two workers, one run).
- [ ] Failures retry with backoff, then mark `failed`; timeouts cancel.
- [ ] Manual run and enable/disable endpoints are audited.

### F8. Workflow and approvals (`easybiz.core.workflow`)

**Purpose:** generic approval flows any module can attach to a document (leave, pay run, purchase order).
**Design:** tables `wf_definition` (`id`, `key` like `hr.leave`, `version`, `entity`, `steps` JSON, `is_active`), `wf_instance` (`id`, `definition` FK, `entity_module`, `entity_type`, `entity_id` uuid, `status` in `running | approved | rejected | cancelled`, `current_step`, `started_by`, `started_at`, `finished_at`), `wf_task` (`id`, `instance` FK, `step`, `assignee_user_id` null, `assignee_role` null, `status` in `open | approved | rejected | skipped | reassigned`, `decided_by`, `decided_at`, `comment`). A step is `{name, approvers: {role|user|org_manager}, mode: any|all, condition?: <ABAC expression>}`; steps run sequentially. Modules declare default definitions in the manifest (`"workflows": [...]`), seeded on enable and editable by tenants (versioned; running instances keep their version).
**Python API:** `workflow.start(key, entity_ref, context) -> instance`; completion publishes `core.workflow.completed` (`{instance_id, key, entity_module, entity_type, entity_id, outcome}`) and the owning module's handler applies the result. Modules never read workflow tables directly.
**Rules:** a user cannot approve their own submission (segregation of duties); only assignees (or holders of `core.workflow.admin`) decide; reassignment and delegation are audited; overdue tasks escalate via jobs (F11); all decisions are audited and publish events.
**API (`/api/core/workflow`):** `GET /inbox` (my open tasks), `POST /tasks/{id}/approve|reject|reassign`, `GET /instances/{id}`, definitions CRUD. Permissions `core.workflow.read|manage|admin`.
**Acceptance**
- [ ] Sequential, `any` and `all` modes, role and org-manager approvers, and conditional steps are tested.
- [ ] Self-approval is impossible; reassign and delegate work; versioned definitions leave running instances untouched.
- [ ] Completion event drives the owning module (migrate HR leave and Payroll run approval onto workflow with tests).
- [ ] Escalation job fires for overdue tasks; notifications (F9) are produced.
- [ ] Isolation, audit and permission tests pass.

### F9. Notifications and webhooks (`easybiz.core.notifications`)

**Purpose:** tell users and external systems about events.
**Design:** tables `notif_notification` (`id`, `user_id`, `kind`, `title`, `body`, `link`, `created_at`, `read_at`), `notif_preference` (`user_id`, `kind`, `channels` JSON), `notif_template` (`kind`, `locale`, `subject`, `body`; Django template syntax), `notif_webhook` (`id`, `url`, `secret`, `events` JSON, `is_active`), `notif_delivery` (`id`, `channel`, `target`, `status`, `attempts`, `last_error`, `payload_ref`). Channels: in-app, email (SMTP or provider via settings F5), webhook. Webhooks are signed with HMAC-SHA256 (`X-Signature: sha256=<hex>`, plus timestamp header), retried with backoff, and disabled after repeated failure. Modules call `notifications.notify(user_ids, kind, context)` or subscribe events to templates declaratively in the manifest.
**API:** `GET /api/core/notifications`, `POST /api/core/notifications/{id}/read`, `POST /api/core/notifications/read-all`, `GET/PUT /api/core/notifications/preferences`, webhooks CRUD (`core.webhooks.manage`) with a "send test" action.
**Acceptance**
- [ ] In-app, email and webhook delivery run through jobs, with retries and delivery records.
- [ ] Webhook signature verifies with the documented algorithm; replay window enforced via timestamp.
- [ ] Preferences suppress channels; templates localise (F12) and fall back to the default locale.
- [ ] Notifications are tenant-isolated and per-user; no content leaks across tenants.

### F10. Files (`easybiz.core.files`)

**Purpose:** attachments and documents with safe storage.
**Design:** table `files_file` (`id` uuid, `storage_key`, `name`, `size`, `mime`, `sha256`, `owner_module`, `owner_type`, `owner_id` null, `status` in `pending | available | quarantined | deleted`, `created_by`, `created_at`). Storage backend is S3-compatible (MinIO in development) with keys `tenants/<schema_name>/<yyyy>/<uuid>`; clients upload through **pre-signed URLs**; the platform enforces MIME allow-list, size limits and per-plan quotas. A virus-scan hook moves files from `pending` to `available` or `quarantined`. Deleting a file is soft first, purged by a retention job.
**API:** `POST /api/core/files` (returns file id and upload URL), `POST /api/core/files/{id}/complete`, `GET /api/core/files/{id}` (metadata), `GET /api/core/files/{id}/download` (short-lived signed URL), `DELETE /api/core/files/{id}`. Permissions `core.files.read|upload|manage`; modules gate access by owner entity.
**Acceptance**
- [ ] Upload then download round-trips with checksum verification against a MinIO test container.
- [ ] A tenant cannot obtain another tenant's object (key prefix and permission tests).
- [ ] MIME and size limits are enforced; quarantined files cannot be downloaded.
- [ ] Quota exceeded returns 413 or 409 with a clear message; deletion and retention purge work.

### F12. Internationalisation and localisation

**Purpose:** languages, time zones and formats per tenant and user.
**Design:** tenant settings (F5) `core.locale` (default language, time zone, currency, week start, number and date formats); user preference `locale` and `timezone` (stored with the membership profile). The API reads `Accept-Language`, falls back to user then tenant default. Storage stays UTC. Modules ship message catalogues (`locale/<lang>/LC_MESSAGES`) and use `gettext_lazy` for user-facing strings, including API error messages and notification templates.
**Acceptance**
- [ ] Error messages and notification templates render in the requested language with fallback.
- [ ] Timestamps are returned in UTC ISO 8601 and converted for display only by clients and templates.
- [ ] Locale resolution order (header, user, tenant, platform default) is tested.
- [ ] A new module can ship a catalogue without core changes.

---

## 16. Authentication hardening

### F13. Authentication hardening

**Purpose:** make login production-grade: sessions that can be revoked, recoverable accounts, second factor, enterprise SSO, machine credentials, and rotatable signing keys.
**Depends on:** F9 (email delivery) for reset and invitations; F5 for tenant security policy.
**Architecture note:** identity tables stay in `public` (D3). Tenant-specific policy (MFA requirement, SSO provider, password rules) lives in tenant settings (F5).

**Design**

1. **Short-lived access tokens plus rotating refresh tokens.** Access TTL 15 minutes. Public table `users_refreshtoken` (`id` uuid, `user` FK, `tenant` FK, `family` uuid, `token_hash` unique (SHA-256 of a 256-bit random value), `created_at`, `expires_at`, `revoked_at`, `replaced_by` null, `user_agent`, `ip`). Every refresh issues a new token and revokes the old one; **presenting an already-revoked token revokes the whole family** (theft detection). Endpoints: `POST /api/auth/refresh`, `POST /api/auth/logout` (revokes the family), `POST /api/auth/logout-all`, `GET /api/auth/sessions`, `DELETE /api/auth/sessions/{family}`.
2. **Password reset.** `POST /api/auth/password/forgot` always answers 202 (no account enumeration); `POST /api/auth/password/reset` consumes a single-use, hashed, 30-minute token, sets the password, revokes all sessions. Both throttled per IP and per email.
3. **Invitations and email verification.** Tenant table `iam_invitation` (`id`, `email`, `roles` JSON, `token_hash`, `expires_at`, `accepted_at`, `invited_by`). `POST /api/core/invitations` (`core.user.manage`), `POST /api/auth/accept-invitation` (sets the password or joins an existing account). Replaces creating users with a password chosen by an admin (the current `POST /core/users` stays for service accounts and tests).
4. **MFA (TOTP, RFC 6238).** Public tables `users_mfadevice` (`user`, `kind`, `secret` encrypted, `confirmed_at`) and `users_recoverycode` (hashed, single-use). When enabled, `POST /api/auth/login` returns `{"mfa_required": true, "mfa_token": "<short-lived>"}` and `POST /api/auth/mfa/verify` completes login. Tenant policy `core.security.require_mfa` is `off | admins | all`. Platform admins always need MFA.
5. **SSO (OIDC; SAML later).** Tenant settings hold providers (`issuer`, `client_id`, encrypted `client_secret`, scopes, allowed email domains, claim-to-role mapping, `jit_provisioning`, `enforce_sso`). Endpoints `GET /api/auth/sso/{provider}/start` and `/callback` use authorization-code flow with PKCE, `state` and `nonce`. A verified email claim maps to a global user; membership is created only when JIT or an invitation allows it.
6. **API keys** (tenant table `iam_apikey`: `id`, `name`, `prefix` unique, `secret_hash`, `permissions` JSON, `expires_at`, `last_used_at`, `created_by`, `revoked_at`). Sent as `Authorization: ApiKey <prefix>.<secret>`. The secret is shown once and stored hashed; comparison is constant-time. Permissions must be a **subset of the creator's**. Keys act as a service principal in audit (`actor_id` = key id, flagged as service). Per-key rate limit. Endpoints `core.apikey.manage`.
7. **Signing keys.** Move JWTs from HS256 to EdDSA or RS256 with `kid`; keep the previous public key valid for the token lifetime; publish `/.well-known/jwks.json` on the platform host. Add claims `jti`, `sid` (refresh family) and `amr` (authentication methods). Key rotation is a documented command.
8. **Brute-force protection.** Throttle per (email, IP) and per IP using a shared cache (Redis) with progressive delay and temporary lockout; identical error for every failure; audit `auth.login.succeeded` and `auth.login.failed` (without the attempted password).
9. **Password policy.** Tenant-configurable minimum length (default 10, current rule), deny-list and optional breached-password check (k-anonymity range query); never log passwords.

**Acceptance criteria**
- [ ] Refresh rotation works; re-presenting a rotated token revokes the family; logout and logout-all revoke immediately (existing access tokens expire within 15 minutes, documented).
- [ ] Reset flow never reveals whether an email exists; tokens are single-use and expire; sessions are revoked on reset.
- [ ] Invitation flow joins new and existing accounts; expired or reused tokens are rejected.
- [ ] TOTP enrolment, verification, recovery codes, and policy enforcement (`admins`, `all`) are tested, including login without MFA being refused when required.
- [ ] OIDC flow tested against a local mock IdP: PKCE, state and nonce validation, JIT provisioning, role mapping, `enforce_sso` blocking password login.
- [ ] API key authentication, subset-permission rule, revocation, expiry and rate limit are tested; the plaintext secret is never stored or logged.
- [ ] Key rotation: tokens signed with the old key validate during overlap and fail afterwards; JWKS output matches.
- [ ] Throttling and lockout work across processes (shared cache) and are tested.
- [ ] The CORS configuration is updated for the refresh cookie decision made with F18 (credentials only for explicit origins).

---

## 17. Authorization v2

### F14. Authorization v2 (role management, ABAC, scoping, caching)

**Purpose:** complete role administration and add attribute-based rules ("approve only if the amount is within your limit and the record is in your branch").
**Depends on:** F3 for org scoping (can start without it).

**Design**

1. **Role management API** (`core.role.manage` unless noted): `GET /api/core/roles/{id}`; `PATCH /roles/{id}` (name, description, full replacement of permissions); `DELETE /roles/{id}` (refused for system roles and for roles still assigned unless `?force=true`); `POST /roles/{id}/clone`; `PUT /api/core/users/{id}/roles` (replace the user's role set), `POST` and `DELETE /users/{id}/roles/{name}`; `GET /api/core/permissions` (assignable permissions for the tenant, grouped by module, with descriptions).
2. **Guards.** Nobody can grant a permission they do not hold (no privilege escalation; `*` holders excepted); the last holder of the `owner` role cannot be removed or demoted; system roles are locked except their description; every change writes an audit row with before and after, and publishes `core.role.changed`.
3. **ABAC.** Tenant table `iam_policy` (`id`, `permission` (code or group pattern), `effect` in `allow_if | deny_if`, `condition` JSON, `priority`, `description`, `is_active`). `condition` is a **declarative expression tree** (operators `eq ne lt lte gt gte in and or not` over `subject.*`, `resource.*`, `context.*`), never executable code. Table `iam_userattribute` (`user_id`, `key`, `value` JSON) supplies subject attributes such as `approval_limit`. Evaluation: RBAC must grant the permission first; any matching `deny_if` denies; if `allow_if` policies exist for that permission, at least one must match. Python API: `authorize(user, "payroll.run.approve", resource={...}, context={...})` and a decorator for endpoints that load the resource first.
4. **Policy tooling.** `POST /api/core/policies/evaluate` (dry run with a sample subject and resource); CRUD under `core.policy.manage`; expression schema validated on save.
5. **Org scope.** Row filtering through `easybiz.core.org.scope.restrict` (F3).
6. **Caching.** Per-request memoisation always; cross-request cache keyed by `(schema, user_id, role_version)` where `role_version` is a counter bumped by any role, assignment or policy change; TTL 60 seconds.

**Acceptance criteria**
- [ ] All role and assignment endpoints work with the guards above, each with a negative test (escalation attempt, last owner, system role edit, delete assigned role).
- [ ] ABAC fixtures cover allow, deny, priority, missing attributes (treated as false), and invalid expressions (rejected on save).
- [ ] A module endpoint using `authorize(...)` with a resource limit is demonstrated in Payroll (approval limit) and tested.
- [ ] Cache invalidation: a permission change takes effect within one request on the same process and within the TTL elsewhere; tested with the version counter.
- [ ] No endpoint evaluates user-supplied code; expression depth and size are capped.
- [ ] Isolation and audit tests pass.

---

## 18. Events v2

### F15. Events v2 (workers, schemas, dead-letter API, retention)

**Purpose:** production-grade event delivery: parallel workers, ordering guarantees, validated payloads, operability.

**Design**

1. **Workers.** Add Celery (Redis or RabbitMQ). Task `dispatch_tenant(schema_name)` claims and delivers events for one tenant. On commit, publishing enqueues `dispatch_tenant` through `transaction.on_commit` (low latency); a beat sweeper enqueues every active tenant periodically as the fallback. `run_dispatcher` stays for development.
2. **Leases instead of long transactions.** Add columns `locked_by`, `locked_until`; status gains `processing`. Claim a batch in a short transaction, run each handler in its own transaction, then finalise. Expired leases are reclaimed. Fairness: per-tenant batch cap and round-robin across tenants.
3. **Ordering.** Optional `ordering_key` (for example the entity id): events with the same key are processed one at a time in `created_at` order.
4. **Schemas and versions.** `events.publishes` entries become objects: `{"name": "...", "version": 1, "payload_schema": {...JSON Schema...}}`. `publish()` validates payloads. Subscribers declare accepted versions; an `@upcast("name", from_version=1)` registry converts old payloads.
5. **Dead-letter API.** `GET /api/core/events?status=&name=&limit=`, `GET /events/{id}`, `POST /events/{id}/replay` (resets failed handlers' inbox state only), `POST /events/{id}/discard`. Permissions `core.events.read|manage`; every action audited.
6. **Retention.** A job deletes `done` events and inbox rows older than N days (tenant setting, default 30); `dead` events are kept until discarded.
7. **Metrics.** Outbox lag (age of the oldest pending event), delivered, retried and dead counters, handler latency histogram, per tenant and module.
8. **Optional bridge** to Kafka or NATS for external consumers, configured per tenant (design only unless required).

**Acceptance criteria**
- [ ] Two workers never deliver the same event twice concurrently; killing a worker mid-batch reclaims events after the lease expires.
- [ ] Per-key ordering is verified with interleaved events; different keys proceed in parallel.
- [ ] Invalid payloads are rejected at publish time; upcasting a version-1 event for a version-2 subscriber is tested.
- [ ] Dead-letter replay re-runs only failed handlers; discard and replay are audited.
- [ ] Retention removes only old `done` events and never touches `dead` or `pending`.
- [ ] Publishing inside a rolled-back transaction enqueues nothing.
- [ ] All existing event tests still pass unchanged.

---

## 19. Platform v2

### F16. Platform v2

**Purpose:** operate many tenants safely: asynchronous provisioning, plans, finer platform roles, support access, export and restore, archival, sharding.
**Depends on:** F11 and F15 (workers), F13 (platform MFA), F10 (storage).

**Design**

1. **Asynchronous provisioning.** Public table `platform_provisioningjob` (`id` uuid, `tenant_slug`, `status` in `queued | running | succeeded | failed | rolled_back`, `steps` JSON (name, status, started, finished, error), `params` JSON without passwords, `requested_by`, `created_at`, `finished_at`). `POST /api/platform/tenants` returns **202** with `{job_id, status_url}` and `GET /api/platform/provisioning/{id}` reports progress; steps are idempotent so a failed job can retry or roll back. A synchronous mode (`?wait=true`, capped) remains for scripts. Same approach for `modules/upgrade`.
2. **Tenant lifecycle states.** `provisioning | active | suspended | pending_deletion`. Deletion becomes two-step: `DELETE` schedules deletion after a grace period (default 14 days, cancellable); a job performs the irreversible drop.
3. **Plans and entitlements.** Public tables `plan_plan` (`key`, `name`, `modules` JSON, `limits` JSON: `users`, `storage_mb`, `api_rate_per_min`), `plan_subscription` (`tenant`, `plan`, `status` in `trial | active | past_due | cancelled`, `period_start`, `period_end`, `trial_ends_at`), `plan_override` (`tenant`, `key`, `value`). Enforced when enabling a module, adding a user, uploading files, and in API rate limiting. Platform endpoints for plans CRUD and assignment; billing integration is out of scope (emit platform events).
4. **Platform roles.** Replace the single flag with roles: `superadmin`, `support`, `billing`, `readonly`, each a set of `platform.*` permissions (`platform.tenant.read|create|suspend|delete`, `platform.module.manage`, `platform.admin.manage`, `platform.impersonate`, `platform.billing.manage`). `PlatformJWTAuth` checks them per endpoint. MFA mandatory.
5. **Impersonation (support access).** `POST /api/platform/tenants/{slug}/impersonate` with `{user_id, reason, ttl_minutes<=15, read_only}` returns a tenant token carrying `imp` (admin id) and `amr`. Add `impersonator_id` to `audit_auditlog`; tenant audit rows record both identities; platform audit records start and end; the UI shows a banner. Requires `platform.impersonate`.
6. **Usage metering.** Daily job writes `usage_snapshot` (public): active users, API calls, storage bytes, events processed, per tenant; endpoints for reporting.
7. **Export and restore.** Export a tenant to a bundle in object storage: `pg_dump -n <schema>` plus the tenant's `public` rows (tenant, domains, memberships, module state), a manifest and checksums. Restore into a new slug, validate, then switch domains. Used for backups, shard moves and offboarding.
8. **Archive on module removal.** `remove_module_data(..., policy="archive")` exports the module's tables (JSONL per table plus schema manifest) to file storage before dropping; records the archive reference; a restore routine re-enables the module and imports (best effort across versions).
9. **Sharding.** `Tenant.db_alias`, multiple `DATABASES`, a router that picks the alias from the current tenant; provisioning places new tenants on the least-loaded shard; `upgrade_modules` iterates shards; moving a tenant uses export and restore. Platform endpoints expose shard load.
10. **Platform events.** Publish platform-level events (`platform.tenant.created`, `.suspended`, `.deleted`, and so on) for integrations.

**Acceptance criteria**
- [ ] Provisioning job reports each step, survives a worker restart, retries from the failed step, and rolls back cleanly on a forced failure (no orphan schema).
- [ ] Deletion is two-step with a cancellable grace period; the drop job runs only after expiry.
- [ ] Plan limits are enforced at each enforcement point with clear 409 or 402-style errors; overrides apply.
- [ ] Each platform role is tested for allowed and denied endpoints; MFA required.
- [ ] Impersonation tokens expire, carry `imp`, are audited on both sides, and honour read-only.
- [ ] Export then restore into a new slug yields identical row counts for all tenant tables; checksum verified.
- [ ] Archive-on-remove produces a restorable archive; restoring recreates the data.
- [ ] Two-shard integration test: tenants land on different databases and all lifecycle operations work on both.

---

## 20. Module system v2

### F17. Module system v2 (scaffold, manifest v2, contract kit, versioned capabilities)

**Purpose:** make writing, validating and operating modules routine and safe. This feature is **P1**: build it before or alongside F1 so HR and Payroll are the first real users.

**Design**

1. **Scaffold.** `python manage.py startmodule <id> [--requires hr] [--optional timesheets] [--path easybiz.modules]` generates: `manifest.json`, `apps.py` (label equals id), `models.py`, `api.py` (router), `handlers.py`, `providers.py`, `migrations/__init__.py`, `tests/` with the contract-kit invocation, and adds the package to `EASYBIZ_MODULES`. The id is validated; existing directories are never overwritten.
2. **Manifest v2** (backward compatible with v1; add `"manifest_version": 2`): `requires_core` (semver range checked against `EASYBIZ_CORE_VERSION`), `provides: [{contract, version}]`, `consumes: [{contract, range, optional}]`, `events.publishes` as objects with versioned payload schemas (F15), `settings` (F5), `jobs` (F11), `numbering` (F7), `workflows` (F8), `custom_fields` (F6), `permissions` with an optional `sensitive: true` flag (F20), `ui` (menus, routes, dashboard widgets for F18). A JSON Schema of the manifest lives at `easybiz/core/kernel/manifest.schema.json` and is enforced at load.
3. **Close the validation gaps from section 5.1:** `provides` must name contracts that exist in `easybiz/core/contracts.py` and that the module actually registers; `consumes` must name existing contracts; a consumed contract that no `requires` module provides must be marked `optional`.
4. **Capability versioning.** Contracts expose `__contract_version__`; providers declare the version they implement; consumers declare a range; the registry resolves, and an incompatible provider counts as unavailable (logged). Contract changes follow semver: additive is minor, breaking is major with a deprecation window.
5. **Contract test kit** (`easybiz/core/testing`, `python manage.py check_module <id>`, `pytest -m module_contract`). `module_harness(module_id, with_=[...], without=[...])` builds a tenant with only that module and its hard dependencies. `run_module_contract_checks(module_id)` verifies:
   - manifest validity and app label;
   - every permission used by the module's endpoints is declared (introspect Ninja operations' auth);
   - every published event is declared and payloads match schemas; every subscription has a handler;
   - **no imports of other modules** (AST scan or `import-linter` contract);
   - **no foreign keys** to other modules' tables, and tables carry the module prefix (introspect `_meta`);
   - migrations are reversible (`migrate zero` then forward);
   - tenant isolation (data in A is invisible in B);
   - lifecycle cycle: enable, disable, remove data, re-enable;
   - handler idempotency (replay the same event twice);
   - the module works alone and with each optional dependency both present and absent;
   - the gate answers 404 when disabled.
6. **System-wide uninstall.** `python manage.py uninstall_module <id>` succeeds only when no tenant has a `TenantModule` row for it; removes catalog and permission rows; code removal remains a deploy step.
7. **Runbook for adding module code.** Document the rolling deploy: build an image containing the new package, deploy, run `upgrade_modules`, enable per tenant. Note the limit (D9).
8. **Module UI contributions.** `GET /api/auth/me` includes the `ui` blocks of enabled modules for the shell (F18).

**Acceptance criteria**
- [ ] `startmodule demo` produces a module that passes `check_module demo` without edits, and refuses to overwrite.
- [ ] The kit runs against Timesheets, HR and Payroll and fails when you deliberately break each rule (negative tests: cross-import, cross-FK, undeclared permission, undeclared event, non-reversible migration, missing handler).
- [ ] Manifest v1 modules still load; v2 fields validate against the JSON Schema; the three validation gaps are closed with tests.
- [ ] Capability version mismatch is treated as unavailable and logged; tested.
- [ ] `uninstall_module` refuses while any tenant has a row, and works afterwards.

---

## 21. Frontend

### F18. Frontend (React shell, module UIs, platform admin)

**Purpose:** a modern UI that adapts to the tenant's enabled modules and the user's permissions, plus an operator console.
**Depends on:** F21 (stable API conventions), F14 (permission model), F13 (login flows). A first slice (login, menu, modules) can start earlier against the current API.

**Design**

- **Repository layout** (`frontend/`, pnpm workspaces): `apps/shell` (tenant app), `apps/platform-admin`, `packages/ui` (components and design tokens), `packages/api-client` (generated from the OpenAPI documents with `openapi-typescript`, plus a thin typed fetch wrapper), `packages/module-sdk` (types and helpers for module UI contributions), `modules/<id>` (a UI package per module).
- **Stack:** React, TypeScript (strict), Vite, TanStack Query, React Router, react-hook-form with zod, Vitest, Playwright. If the organisation has a design system (this project includes `easybiz-design-system.html`), derive the tokens from it rather than inventing new ones.
- **Shell behaviour:** the tenant is the host; login supports MFA and SSO; the access token lives in memory and refresh uses an httpOnly, `SameSite=Strict` cookie scoped to `/api/auth` (this needs CORS credentials for explicit origins; update F13/section 6.5 accordingly). `GET /api/auth/me` drives the menu and permission-aware components (`<Can permission="...">`). Module UIs are lazy-loaded from the `ui` contributions of enabled modules. Errors map to consistent UI: 401 to login, 403 to "not allowed", 404 for a disabled module to a clear "module not enabled" page, 409 and 422 to inline messages from the error envelope (F21).
- **Core admin screens:** users and invitations, roles with a permission matrix, modules (enable and disable with dependency explanations from `blocked_by`), audit log, settings, org tree, custom fields, workflow inbox and designer (basic), notifications, jobs, files, API keys, sessions.
- **Platform admin app (platform host):** login with MFA, overview dashboard, tenant list and detail, create wizard (server-side validation messages), suspend, resume and delete with typed confirmation, domains, per-tenant module toggles, module catalog with upgrade state, platform admins and roles, audit viewer, provisioning progress.
- **Quality:** WCAG 2.1 AA, responsive, i18n-ready (F12), bundle size budget per route, no secrets in the bundle.

**Acceptance criteria**
- [ ] Playwright end-to-end flows pass in CI: login, menu reflects permissions, enabling a module makes its menu and routes appear without reload of the app code, disabled module page, role edit.
- [ ] The generated API client is regenerated in CI and the build fails on type errors from API changes.
- [ ] Accessibility checks (axe) pass on the main screens; keyboard navigation works.
- [ ] Platform admin flows pass: create tenant with job progress, suspend and resume, typed-confirmation delete, module toggle.
- [ ] Impersonation shows a persistent banner and read-only mode disables write controls.

---

## 22. Operations, security, API conventions, performance

### F21. API conventions

**Purpose:** one predictable API style across core and modules, with a safe path from today's unversioned responses.

**Design**

1. **Error envelope.** Keep `detail`; add `code` (stable, machine readable), `errors` (field list for 422) and `request_id`: `{"detail": "...", "code": "module.not_enabled", "errors": [{"field": "hours", "code": "range", "message": "..."}], "request_id": "..."}`. Code catalogue in appendix E.
2. **Versioning.** Introduce `/api/v1/` for the new conventions; keep today's `/api/` working as v0 with `Deprecation` and `Sunset` headers. Breaking changes require a new version; additive changes do not.
3. **Pagination and filtering.** Lists return `{"items": [...], "next_cursor": "...", "count": n?}` with `?limit=` (max 200) and `?cursor=`; sorting `?sort=-created_at`; filters `?field=value`, `?field__in=a,b`, `?q=`. (Today most list endpoints return bare arrays, and the platform tenant list uses limit and offset.)
4. **Idempotency.** `Idempotency-Key` header on creating and action `POST`s; tenant table `idem_key` (`key`, `endpoint`, `request_hash`, `status`, `body`, `expires_at`); same key and payload replays the stored response; same key with a different payload returns 422.
5. **Optimistic concurrency.** Mutable resources carry `version` and an `ETag`; `PATCH` and `PUT` require `If-Match` (412 on mismatch, 428 when missing).
6. **Async operations.** Long operations answer 202 with a job reference (F11, F16).
7. **OpenAPI hygiene.** Tags, examples, documented error responses and auth on every operation; an OpenAPI diff check in CI (for example `oasdiff`) blocks accidental breaking changes; the TypeScript client is generated from the schema.

**Acceptance criteria**
- [ ] All endpoints return the new envelope under `/api/v1/`; v0 behaviour is unchanged and flagged deprecated.
- [ ] A helper makes cursor pagination and filters reusable by modules; tested on at least two modules.
- [ ] Idempotent replay, payload mismatch, concurrent duplicate requests (one execution) are tested.
- [ ] Concurrency conflicts return 412; missing `If-Match` returns 428.
- [ ] The CI diff check fails on a deliberately breaking change.

### F19. Observability and operations

**Design**
1. **Logging.** Structured JSON logs with `request_id`, `tenant`, `user_id`, route and latency. Middleware sets and returns `X-Request-ID`.
2. **Metrics.** Prometheus endpoint: request latency and status by route, DB timings, outbox lag, event delivery counters, job runs, migration state per module, active tenants.
3. **Health.** `/health/live` (process) and `/health/ready` (database, broker, storage) on the platform host.
4. **Errors and traces.** Sentry (or compatible) and OpenTelemetry tracing across request, job and event spans.
5. **Containers.** Multi-stage `Dockerfile` (non-root, gunicorn with uvicorn workers), `docker-compose.full.yml` (app, worker, beat, Redis, PostgreSQL, MinIO, mail catcher), Kubernetes manifests or a Helm chart (deployment, worker, beat, migration job, HPA).
6. **CI.** Pipeline: lint (ruff), type-check (mypy on `easybiz.core`), `makemigrations --check`, tests on a PostgreSQL service, OpenAPI diff, image build, vulnerability scan.
7. **Runbooks.** Backup and restore (per-schema and PITR), module upgrade and rollback, tenant export, incident response, key rotation.
8. **Configuration.** All settings from environment variables with a documented schema; startup fails fast on missing production secrets.

**Acceptance criteria**
- [ ] Every request log line contains `request_id` and `tenant`; the id is returned in the response header and in error bodies.
- [ ] Metrics endpoint exposes the listed series; a test asserts their presence.
- [ ] Readiness fails when the database is unreachable.
- [ ] `docker compose -f docker-compose.full.yml up` yields a working system (provision a tenant, log in, enable a module).
- [ ] CI runs all stages and fails on a lint error, a missing migration, and a breaking API change.
- [ ] Runbooks exist and the restore runbook is exercised once in CI or a scripted drill.

### F20. Security and compliance

**Design**
1. **HTTP hardening.** HSTS, `X-Content-Type-Options`, `Referrer-Policy`, a strict CORS allow-list in production, request body size limits, and trusted-proxy configuration for client IPs.
2. **Rate limits.** Per tenant and per user (shared cache) for login, API keys and general API traffic; plan-aware (F16).
3. **Database roles.** Separate roles: a migration role (DDL) and a runtime role (no `DROP`, no `CREATE SCHEMA`); schema-creation performed by a provisioning role only.
4. **Audit integrity.** Append-only audit tables (revoke `UPDATE` and `DELETE` for the runtime role); retention policy per tenant; export endpoint; auditing of **reads of sensitive data** for permissions flagged `sensitive` in manifests (payroll, contracts).
5. **GDPR.** Per-person export (global account plus per-tenant references by UUID across modules through an `erase`/`export` handler contract that modules implement) and erasure or anonymisation with an audit record. Modules declare PII fields in the manifest.
6. **Secrets.** Encryption of stored secrets (Fernet key from environment, rotation procedure); no secrets in logs or error bodies; dependency scanning in CI.
7. **Cross-tenant guard tests.** A generic test walks every list and detail endpoint with a token of tenant A against identifiers of tenant B and expects 404 or 403; a schema-leak test asserts `search_path` is restored after every request, job and event.
8. **Threat model.** Document the assets, trust boundaries and abuse cases (token theft, tenant confusion, privilege escalation, module supply chain, SSRF through webhooks) and the mitigations.

**Acceptance criteria**
- [ ] The runtime database role cannot drop tables or schemas (tested by attempting it).
- [ ] Audit rows cannot be modified or deleted by the application role.
- [ ] Reads of `sensitive` permissions are audited; tests cover payroll and contracts.
- [ ] Person export and erase work across core and both modules and are audited.
- [ ] The cross-tenant guard test covers every registered route and runs in CI.
- [ ] Webhook delivery blocks private and link-local addresses (SSRF test).
- [ ] The threat model document exists and each listed mitigation maps to a test or a control.

### F22. Performance and scale

**Proposed initial targets (validate against a baseline, then adjust):** p95 below 200 ms for read endpoints and below 400 ms for writes at 200 requests per second per two workers; event delivery lag p95 below 5 seconds; provisioning under 30 seconds; module enable under 15 seconds.

**Design**
1. **Cache enabled-module checks** (per tenant, version-stamped in Redis, invalidated on every lifecycle change) because the gate and capability lookups currently hit the database on every request.
2. **Permission and policy caches** (F14) and prefetching to avoid N+1 queries in list endpoints (add `assertNumQueries`-style tests).
3. **Parallel migrations.** `upgrade_modules --parallel N` with per-tenant status, resumable after failure; a dry-run mode that lists pending migrations per tenant.
4. **Connections.** PgBouncer in session mode (or transaction mode with `SET LOCAL search_path` per transaction, verified); connection health checks; document pool sizing.
5. **Indexes and retention.** Review indexes on audit, outbox and entry tables; partition `events_outboxevent` and `audit_auditlog` by month for large tenants; archive old audit rows.
6. **Load tests** (k6 or Locust) with a seeded multi-tenant dataset (for example 200 tenants, 20 users each) producing a baseline report checked into the repository.
7. **Scale limits.** Measure migration time and catalog size versus schema count; define the threshold that triggers sharding (F16).

**Acceptance criteria**
- [ ] The gate adds no database query per request on a warm cache; invalidation is tested across processes.
- [ ] List endpoints have query-count tests.
- [ ] `upgrade_modules --parallel` upgrades 50 tenants and resumes correctly after a simulated failure.
- [ ] A load-test report with the measured baseline against the targets is committed.
- [ ] A documented rule states at what schema count and migration duration a new shard is added.

---

## Appendix A. Manifest example (the real Timesheets manifest, version 1 format)

```json
{
  "id": "timesheets",
  "name": "Timesheets",
  "version": "0.1.0",
  "requires": [],
  "optional": [],
  "provides": ["AttendanceProvider"],
  "consumes": [],
  "permissions": [
    {"code": "timesheets.project.read", "description": "See projects"},
    {"code": "timesheets.project.manage", "description": "Create and edit projects"},
    {"code": "timesheets.entry.create", "description": "Log and submit your own time"},
    {"code": "timesheets.entry.read", "description": "See your own time entries"},
    {"code": "timesheets.entry.approve", "description": "See everyone's entries; approve or reject submitted time"}
  ],
  "roles": [
    {
      "name": "timesheet_user",
      "description": "Logs own time",
      "permissions": ["timesheets.project.read", "timesheets.entry.create", "timesheets.entry.read"]
    },
    {
      "name": "timesheet_approver",
      "description": "Logs own time and approves others'",
      "permissions": ["timesheets.project.read", "timesheets.project.manage", "timesheets.entry.create", "timesheets.entry.read", "timesheets.entry.approve"]
    }
  ],
  "events": {
    "publishes": ["timesheets.entry.approved", "timesheets.entry.rejected"],
    "subscribes": ["core.membership.removed"]
  },
  "menu": [
    {"label": "Timesheets", "route": "/timesheets", "permission": "timesheets.entry.read"},
    {"label": "Projects", "route": "/timesheets/projects", "permission": "timesheets.project.manage"}
  ]
}
```

Sketch of the **manifest v2** additions (F17), shown only for the new keys:

```json
{
  "manifest_version": 2,
  "requires_core": "^1.0",
  "provides": [{"contract": "EmployeeProvider", "version": "1.0"}],
  "consumes": [{"contract": "AttendanceProvider", "range": "^1.0", "optional": true}],
  "events": {
    "publishes": [{"name": "hr.employee.terminated", "version": 1,
                   "payload_schema": {"type": "object", "required": ["employee_id"],
                                       "properties": {"employee_id": {"type": "string", "format": "uuid"}}}}],
    "subscribes": ["core.membership.removed"]
  },
  "settings": {"schema": {"type": "object", "properties": {"leave_year_start": {"type": "string"}}},
               "defaults": {"leave_year_start": "01-01"}},
  "jobs": [{"name": "accrue-leave", "cron": "0 3 1 * *", "handler": "easybiz.modules.hr.jobs:accrue_leave"}],
  "numbering": [{"key": "hr.employee", "pattern": "EMP-{seq:05d}", "reset": "never"}],
  "workflows": [{"key": "hr.leave", "entity": "hr.leaverequest", "steps": [{"name": "manager", "approvers": {"org_manager": true}, "mode": "any"}]}],
  "custom_fields": ["hr.employee"],
  "permissions": [{"code": "hr.contract.read", "description": "See contract terms", "sensitive": true}],
  "ui": {"menu": [{"label": "People", "route": "/hr/employees", "permission": "hr.employee.read"}]}
}
```

## Appendix B. Environment variables

| Variable | Status | Meaning |
|---|---|---|
| `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS` | current | Core Django settings |
| `EASYBIZ_DB_NAME`, `EASYBIZ_DB_USER`, `EASYBIZ_DB_PASSWORD`, `EASYBIZ_DB_HOST`, `EASYBIZ_DB_PORT` | current | Database connection |
| `EASYBIZ_JWT_TTL_SECONDS`, `EASYBIZ_PLATFORM_JWT_TTL_SECONDS` | current | Token lifetimes (planned default for tenant tokens: 900 with F13) |
| `EASYBIZ_PLATFORM_LOGIN_RATE` | current | Platform login throttle, for example `10/m` |
| `EASYBIZ_CORS_ORIGINS` | current | Allowed origins in production |
| `EASYBIZ_REDIS_URL` | planned (F15, F13, F22) | Cache, throttling, Celery broker |
| `EASYBIZ_SECRETS_KEY` | planned (F5, F13) | Fernet key for encrypting stored secrets |
| `EASYBIZ_JWT_PRIVATE_KEY`, `EASYBIZ_JWT_PUBLIC_KEYS` | planned (F13) | Signing key and accepted public keys (`kid` map) |
| `EASYBIZ_STORAGE_*` (endpoint, bucket, access key, secret, region) | planned (F10) | S3-compatible object storage |
| `EASYBIZ_EMAIL_*` | planned (F9) | SMTP or provider configuration |
| `EASYBIZ_SENTRY_DSN`, `EASYBIZ_OTEL_EXPORTER_OTLP_ENDPOINT` | planned (F19) | Error and trace reporting |
| `EASYBIZ_SHARDS` | planned (F16) | JSON list of database aliases and URLs |

## Appendix C. Permission catalogue

**Current:** `core.module.read`, `core.module.manage`, `core.role.read`, `core.role.manage`, `core.user.read`, `core.user.manage`, `core.audit.read`; `timesheets.project.read`, `timesheets.project.manage`, `timesheets.entry.create`, `timesheets.entry.read`, `timesheets.entry.approve`.

**Planned:**

| Group | Codes |
|---|---|
| HR (F1) | `hr.employee.read`, `hr.employee.manage`, `hr.contract.read` (sensitive), `hr.contract.manage`, `hr.leave.request`, `hr.leave.approve`, `hr.leave.read_all` |
| Payroll (F2) | `payroll.component.manage`, `payroll.compensation.read` (sensitive), `payroll.compensation.manage`, `payroll.run.read`, `payroll.run.create`, `payroll.run.approve`, `payroll.payslip.read` (sensitive) |
| Core services | `core.org.read`, `core.org.manage`, `core.org.scope.all`, `core.numbering.read\|manage`, `core.settings.read\|manage`, `core.flags.manage`, `core.party.read\|manage`, `core.item.read\|manage`, `core.currency.read\|manage`, `core.customfields.read\|manage`, `core.jobs.read\|manage`, `core.workflow.read\|manage\|admin`, `core.webhooks.manage`, `core.files.read\|upload\|manage`, `core.apikey.manage`, `core.policy.manage`, `core.events.read\|manage` |
| Platform (F16) | `platform.tenant.read\|create\|suspend\|delete`, `platform.module.manage`, `platform.admin.manage`, `platform.impersonate`, `platform.billing.manage` |

## Appendix D. Event catalogue

| Event | Producer | Payload | Status |
|---|---|---|---|
| `core.module.enabled` | core | `{module, version}` | current |
| `core.module.disabled` | core | `{module}` | current |
| `core.membership.removed` | core | `{user_id}` | current |
| `timesheets.entry.approved` / `.rejected` | timesheets | `{entry_id, user_id, project_id, work_date, hours}` | current |
| `hr.employee.hired` / `.updated` | hr | `{employee_id, user_id}` | planned (F1) |
| `hr.employee.terminated` | hr | `{employee_id, user_id, effective_date}` | planned (F1) |
| `hr.leave.approved` | hr | `{employee_id, leave_id, start_date, end_date, leave_type}` | planned (F1) |
| `payroll.run.approved` / `.paid` | payroll | `{run_id, period_start, period_end}` | planned (F2) |
| `payroll.payslip.issued` | payroll | `{payslip_id, employee_id, run_id}` | planned (F2) |
| `core.org.unit.created` / `.updated` / `.moved` / `.deactivated` | core | `{unit_id, ...}` | planned (F3) |
| `core.party.changed`, `core.item.changed` | core | `{id, change}` | planned (F4) |
| `core.workflow.completed` | core | `{instance_id, key, entity_module, entity_type, entity_id, outcome}` | planned (F8) |
| `core.role.changed` | core | `{role_id}` | planned (F14) |
| `platform.tenant.created` / `.suspended` / `.deleted` | platform (public schema, not the tenant outbox) | `{slug}` | planned (F16) |

## Appendix E. Error code catalogue (planned with F21; `detail` stays human-readable)

| Code | HTTP | Meaning |
|---|---|---|
| `auth.invalid_credentials` | 401 | Wrong email or password, or no membership |
| `auth.token_invalid` / `auth.token_expired` | 401 | Bad or expired token |
| `auth.mfa_required` | 401 | Second factor needed |
| `auth.forbidden` | 403 | Missing permission (message names it) |
| `tenant.suspended` | 403 | Tenant suspended |
| `module.not_enabled` | 404 | Module not enabled for this tenant |
| `module.dependency_missing` | 409 | A required module is not enabled |
| `module.dependents_enabled` | 409 | Cannot disable or remove: other modules need it |
| `module.not_disabled` | 409 | Disable the module first |
| `request.confirmation_required` | 400 | Missing `confirm` or `confirm_slug` |
| `validation.failed` | 422 | Field errors in `errors[]` |
| `resource.not_found` | 404 | Unknown id |
| `resource.conflict` | 409 | State conflict or duplicate |
| `resource.version_mismatch` | 412 | `If-Match` failed |
| `resource.precondition_required` | 428 | `If-Match` missing |
| `rate.limited` | 429 | Throttled |
| `plan.limit_reached` | 409 | Plan limit hit |
| `idempotency.payload_mismatch` | 422 | Same key, different body |

## Appendix F. Status values

| Entity | Values |
|---|---|
| Tenant | `is_active` true or false today; later `provisioning`, `active`, `suspended`, `pending_deletion` |
| `TenantModule.status` | `enabling`, `enabled`, `disabled` (no row means not enabled or removed) |
| Module catalog state (platform API) | `installed`, `not_installed`, `upgrade_pending`, `missing_code` |
| `OutboxEvent.status` | `pending`, `done`, `dead` (later `processing`) |
| Timesheet entry | `draft`, `submitted`, `approved`, `rejected` |

## Appendix G. Developer command cheat sheet

```bash
docker compose up -d db
uv sync
uv run manage.py migrate_schemas --shared
uv run manage.py init_platform
uv run manage.py create_platform_admin --email root@example.com --password a-long-admin-pass
uv run manage.py provision_tenant acme --name "Acme" --domain acme.localhost \
    --owner-email owner@acme.test --owner-password change-me-now --modules timesheets
uv run manage.py runserver                     # platform: http://localhost:8000/api/platform/docs
                                               # tenant:   http://acme.localhost:8000/api/docs
uv run manage.py run_dispatcher                # event worker (second terminal)
uv run manage.py tenant_module acme disable timesheets
uv run manage.py upgrade_modules               # after deploying new module code
uv run pytest                                  # creates and drops database easybiz_test
uv run manage.py makemigrations --check --dry-run
```

## Appendix H. Kickoff prompts for Claude Code

**Rebuild the baseline (Part A)**

> Read `ERP-CORE-SPEC.md` sections 0 to 12 completely. Build milestones M0 to M9 from section 11 in order. After each milestone run its verification and the tests that exist so far, then commit with the milestone id in the message. Treat section 2.3 (invariants) and section 12.2 (pitfalls) as binding. Do not add features that are not in Part A. At the end, run the full suite and confirm all 85 tests from section 10 exist and pass.

**Build one remaining feature (Part B)**

> Read `ERP-CORE-SPEC.md` sections 0 to 3, 5, 6 and 12, then the section for feature `F<n>` and its dependencies in the index (13.1). Write the tests for the acceptance criteria first, then implement until they pass. Follow the Definition of done (0.3) and the rules for new core services (13.3). Update the appendices (permissions, events, environment variables) and `README.md`. Do not change an invariant; if you believe one must change, stop and write a proposal instead.

**Review a change against the spec**

> Review the diff against `ERP-CORE-SPEC.md`. List every violated invariant (2.3), every pitfall from 12.2 that was repeated, missing acceptance criteria, missing audit rows, undeclared permissions or events, and any cross-module import or foreign key. Do not rewrite code; report findings with file and line.

## Appendix I. Open questions to confirm before building Part B

1. **Refresh token transport** (F13 and F18): httpOnly cookie plus CORS credentials, or tokens in a JavaScript-managed store. The spec assumes the cookie.
2. **API versioning** (F21): the spec assumes introducing `/api/v1/` and deprecating `/api/`. Confirm that nothing external depends on today's response shapes.
3. **Broker** (F15): Celery with Redis assumed; RabbitMQ is the alternative if durable queues are required.
4. **SSO scope** (F13): OIDC only first; is SAML required for launch customers?
5. **Object storage** (F10, F16): S3-compatible assumed. Which provider in production?
6. **Plans and billing** (F16): entitlements only (as specified), or an actual billing provider integration?
7. **Hosting and sharding** (F16, F22): single PostgreSQL first, or multi-shard from day one?
8. **Compliance targets** (F20): GDPR assumed. Are SOC 2 or ISO 27001 evidence requirements in scope?
9. **Initial vertical modules**: after HR and Payroll, which module comes next (SCM, manufacturing, finance)?
