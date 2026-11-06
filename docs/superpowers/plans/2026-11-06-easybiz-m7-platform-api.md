# Easybiz M7 (Platform Admin API) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the platform (operator) plane served on the public host — platform-scoped JWT auth, and the `/api/platform/*` API to manage tenants, their domains and modules, the module catalog, and platform admins — plus the platform audit log and the `create_platform_admin` bootstrap command.

**Architecture:** A second `NinjaAPI` (`urls_namespace="platform_api"`) mounted by `config/urls_public.py` (the public-schema URLconf), guarded by `PlatformJWTAuth` (public host only; `scope="platform"` tokens; `is_platform_admin` read live each request). Endpoints are thin handlers that call the already-built `kernel/tenants.py`, `kernel/provisioning.py`, `kernel/lifecycle.py`, and `kernel/registry` services, and record a `PlatformAuditLog` row per mutation. Tenant data stays in tenant schemas; platform catalog/audit live in `public` (invariant I3). Platform and tenant tokens are not interchangeable (I9).

**Tech Stack:** Django 6.1 + django-tenants, django-ninja (`NinjaAPI`, `Router`, `HttpBearer`, `Status`, `HttpError`, throttling), PyJWT (HS256), PostgreSQL 16, pytest on real Postgres; `uv`.

**Spec:** `ERP-CORE-SPEC.md` — §6 (platform services: provisioning/tenants, identity/auth, authz, audit), §7.2 (platform API reference), §10 `test_platform_api.py` (24 tests), M7 (§11). Invariants I3 (tenant data in tenant schema, platform data in public), I9 (token scoping/host binding), I14 (provisioning all-or-nothing), D12 (platform admin is a boolean flag on the global user).

## Current state (verified against the tree)

Already built (M3b) — do **not** rebuild:
- `User.is_platform_admin: bool` (public `users_user`).
- `easybiz/core/kernel/tenants.py`: `validate_new_tenant`, `schema_name_for`, `normalize_domain`, `suspend`, `resume`, `add_domain`, `remove_domain`, `delete_tenant(tenant, confirm_slug)`.
- `easybiz/core/kernel/provisioning.py`: `provision_tenant(...)` — already validates via `validate_new_tenant` and rolls back all-or-nothing (drops schema + deletes tenant row) on any exception (I14).
- `easybiz/core/kernel/lifecycle.py`: `enable_module`/`disable_module`/`remove_module_data`/`sync_catalog`/`upgrade_modules`.
- `TenantStatusMiddleware` already returns 403 on a suspended tenant (`is_active is False`) for every path; `run_dispatcher` already skips inactive tenants.
- Tenant auth in `easybiz/core/api/security.py` (`encode_tenant_token`, `decode_token`, `TenantJWTAuth`); settings `EASYBIZ_PLATFORM_JWT_TTL_SECONDS=1800`.
- `config/urls_public.py`: currently `/health` only. `config/urls.py`: tenant `/api/`.

To build (this milestone): `PlatformAuditLog` + `record_platform`; platform token + `PlatformJWTAuth`; `create_platform_admin`; `easybiz/core/platform_api/*` (NinjaAPI + routers) mounted on `urls_public` with docs; the endpoints in §7.2; `EASYBIZ_PLATFORM_LOGIN_RATE` + throttled login; conftest platform test helpers.

## Scope rulings

- **Ruling (reuse, don't duplicate):** every tenant mutation delegates to the existing `kernel` services (`provision_tenant`, `suspend`/`resume`/`add_domain`/`remove_domain`/`delete_tenant`, `enable_module`/…). The platform handler's job is auth + request parsing + calling the service + `record_platform` + serialising the `Tenant` object. No business logic is re-implemented in `platform_api`.
- **Ruling (audit split, §6.4):** platform actions write `PlatformAuditLog` in `public` via `record_platform` (actor = the platform admin). This is separate from the tenant-schema `audit_auditlog` that `provision_tenant`/`lifecycle` already write; both happen (platform-level and tenant-level).
- **Ruling (test count):** the spec catalogues 24 `test_platform_api.py` behaviours. They are distributed across Tasks 3–8 by area; the file may be split per area for readability (e.g. `test_platform_auth.py`, `test_platform_tenants.py`, …) — a reviewer should count behaviours, not one filename.

## Global Constraints

- Python 3.13; Django ≥5.2 (6.1); PostgreSQL 16; `uv`; pytest (real Postgres).
- §0.5: reads in `queries`/writes+rules in `commands` or a `service` (platform handlers call kernel services; serialisers live beside the router or in a `types.py`); types in `types.py`; thin handlers (parse → call → `record_platform` → serialise), domain errors mapped centrally via `DomainError` where applicable; no module docstrings; concise single docstrings; imports at top; named predicates past two conditions; **comments short and plain**; `ruff`/`ruff format --check`/`mypy easybiz config` clean; `makemigrations --check` clean; short commits, **no attribution**.
- I3: `PlatformAuditLog` is a public (shared) model. I9: platform tokens carry `scope="platform"`, are accepted only on the public host, and tenant tokens are rejected there (and vice-versa). D12: platform admin = `User.is_platform_admin`.
- §7.2 values: platform prefix `/api/platform`; all endpoints need a platform token except `POST /auth/login`; `limit` max 200; the platform (`public`) tenant is excluded from tenant listings; **P8 route order** — register `/modules/sync` and `/modules/upgrade` before `/modules/{id}`.
- Platform token TTL `EASYBIZ_PLATFORM_JWT_TTL_SECONDS` (1800). Login throttled per client IP via `EASYBIZ_PLATFORM_LOGIN_RATE` (429 when exceeded).

## Review Focus

- **Token non-interchangeability + host binding (I9):** a tenant token is rejected (401) by the platform API; a platform token is rejected (401) by the tenant API; the platform API is unreachable (404) on a tenant host and `TenantJWTAuth` returns 401 on the public host. → Tasks 2–3.
- **Demotion is immediate:** `is_platform_admin` is read from the DB every request, so an admin demoted after issuing a token is refused on the next call with the old token. → Tasks 2–3.
- **Provisioning rollback (I14):** a create that fails after the schema/domain exist leaves **no** tenant row, schema, or domain behind. → Task 5.
- **Suspend truly blocks:** a suspended tenant rejects tenant login, tenant API calls with a pre-suspension token, and `/api/docs` (403), and resume restores all three. → Task 5.
- **Delete safety:** `DELETE /tenants/{slug}` requires the tenant already suspended (409) and `confirm_slug` equal to the slug (422), drops the schema, and keeps the user rows. → Task 5.
- **Route-order P8:** `GET /modules/sync`-style fixed paths resolve before `/modules/{id}`, so `sync`/`upgrade` aren't swallowed as an `{id}`. → Task 7.
- **Last-of-kind guards:** removing the last domain of a tenant (409), and deleting the last platform admin or yourself (409). → Tasks 6, 8.

---

### Task 1: Platform audit log (`PlatformAuditLog` + `record_platform`)

**Files:**
- Modify: `easybiz/core/tenancy/models.py`; Create: `easybiz/core/tenancy/audit.py`, `easybiz/core/tenancy/migrations/000N_platformauditlog.py` (generated)
- Test: `tests/test_platform_audit.py`

**Interfaces:**
- Produces: `PlatformAuditLog(id, at, actor_id, actor_email, action, target, detail)` (public/shared); `record_platform(actor, action, target="", detail=None) -> PlatformAuditLog`.

- [ ] **Step 1: Failing test** — `tests/test_platform_audit.py`:

```python
def test_record_platform_writes_row(request):  # public schema via autouse fixtures (no `db`)
    from easybiz.core.tenancy.audit import record_platform
    from easybiz.core.tenancy.models import PlatformAuditLog
    from easybiz.core.users.models import User

    actor = User.objects.create(email="ops@easybiz.test", is_platform_admin=True)
    row = record_platform(actor, "tenant.created", target="acme", detail={"modules": ["timesheets"]})
    assert row.actor_email == "ops@easybiz.test" and row.action == "tenant.created"
    assert PlatformAuditLog.objects.filter(target="acme").exists()
```
(Use a cleanup finalizer to delete the user, per the commit-real-data convention.)

- [ ] **Step 2: Run — expect fail** (model/service missing).

- [ ] **Step 3: Implement** the model in `tenancy/models.py` (shared app): `id` uuid pk, `at` auto_now_add (db_index), `actor_id` UUIDField null, `actor_email` CharField(254, blank), `action` CharField(64, db_index), `target` CharField(120, blank, db_index), `detail` JSONField(default=dict). `tenancy/audit.py`: `record_platform(actor, action, target="", detail=None)` captures `actor.id`/`actor.email` (tolerating `None` actor) and creates the row.

- [ ] **Step 4: Migration** `uv run manage.py makemigrations tenancy`; **Step 5:** run tests green; **Step 6:** gate + commit `git commit -m "Add platform audit log model and record_platform"`.

---

### Task 2: Platform token, `PlatformJWTAuth`, and `create_platform_admin`

**Files:**
- Create: `easybiz/core/api/platform_security.py`; Modify: `config/settings.py` (`EASYBIZ_PLATFORM_LOGIN_RATE`); Create: `easybiz/core/kernel/management/commands/create_platform_admin.py`
- Test: `tests/test_platform_security.py`

**Interfaces:**
- Produces: `encode_platform_token(user_id) -> str` (claims `sub`, `scope="platform"`, `iat`, `exp` from `EASYBIZ_PLATFORM_JWT_TTL_SECONDS`); `PlatformJWTAuth(HttpBearer)` → the `User` when valid else `None`; `platform_auth = PlatformJWTAuth()`. `create_platform_admin --email --password [--name]` (create-or-promote).
- Consumes: `decode_token` (reuse from `security.py`), `get_public_schema_name`, `User`.

- [ ] **Step 1: Failing tests** — `tests/test_platform_security.py`:

```python
def test_platform_token_roundtrip_scope():
    from easybiz.core.api.platform_security import encode_platform_token
    from easybiz.core.api.security import decode_token
    tok = encode_platform_token("11111111-1111-1111-1111-111111111111")
    assert decode_token(tok)["scope"] == "platform"


def test_create_platform_admin_creates_then_promotes(request):
    from django.core.management import call_command
    from easybiz.core.users.models import User
    call_command("create_platform_admin", "--email", "ops@easybiz.test", "--password", "change-me-now")
    assert User.objects.get(email="ops@easybiz.test").is_platform_admin is True
    # idempotent promote of an existing user
    User.objects.create(email="old@easybiz.test")
    call_command("create_platform_admin", "--email", "old@easybiz.test")
    assert User.objects.get(email="old@easybiz.test").is_platform_admin is True
```
(Cleanup finalizer for the created users.)

- [ ] **Step 2: Run — expect fail.**

- [ ] **Step 3: Implement.** `platform_security.py`: `encode_platform_token` (mirror `encode_tenant_token`, `scope="platform"`, TTL `EASYBIZ_PLATFORM_JWT_TTL_SECONDS`). `PlatformJWTAuth.authenticate(request, token)`: return `None` unless `request.tenant.schema_name == get_public_schema_name()`; `decode_token`; require `payload.get("scope") == "platform"` and `sub`; load `User.objects.filter(id=sub, is_active=True, is_platform_admin=True).first()` (live read → demotion immediate); return it or `None`. `create_platform_admin.py`: `User.objects.update_or_create(email=…, defaults with is_platform_admin=True)`, set password if given, reject new account without a password (≥10 chars via the existing rule). `settings.py`: `EASYBIZ_PLATFORM_LOGIN_RATE = os.environ.get("EASYBIZ_PLATFORM_LOGIN_RATE", "10/m")`.

- [ ] **Step 4: Run green; Step 5: gate + commit** `git commit -m "Add platform JWT auth and create_platform_admin command"`.

---

### Task 3: `platform_api` scaffold + auth endpoints + public-host wiring + docs

**Files:**
- Create: `easybiz/core/platform_api/__init__.py`, `easybiz/core/platform_api/types.py`, `easybiz/core/platform_api/auth.py`; Modify: `config/urls_public.py`, `tests/conftest.py`
- Test: `tests/test_platform_auth_api.py`

**Interfaces:**
- Produces: `platform_api` (`NinjaAPI(urls_namespace="platform_api", docs at /api/platform/docs)`); `POST /api/platform/auth/login` (throttled), `GET /api/platform/me`. conftest: an `admin` fixture (creates a platform admin + returns `(user, token)`) and a `plat` client helper (HTTP_HOST `localhost`, Bearer).
- Consumes: Task 2 auth, `users.authenticate`-style credential check against the global user (no tenant membership — platform login is global).

- [ ] **Step 1: Failing tests** — `tests/test_platform_auth_api.py` (via `django.test.Client`, `HTTP_HOST="localhost"`):
  - `test_login_returns_token` — valid admin creds → 200 `{access_token,…}`.
  - `test_bad_credentials_401`, `test_missing_token_401`.
  - `test_tenant_owner_is_not_platform_admin` — a tenant owner's creds → 401 at platform login.
  - `test_tokens_not_interchangeable` — a tenant token on `/api/platform/me` → 401; a platform token on a tenant host `/api/auth/me` → 401.
  - `test_platform_api_absent_on_tenant_host` — `GET /api/platform/me` on `acme.localhost` → 404.
  - `test_login_rate_limited_429` — exceeding `EASYBIZ_PLATFORM_LOGIN_RATE` → 429.
  - `test_demoted_admin_loses_access` — issue token, set `is_platform_admin=False`, next `/me` → 401.

- [ ] **Step 2: Run — expect fail.**

- [ ] **Step 3: Implement.** `platform_api/__init__.py`: build the `NinjaAPI`, `add_router("/auth", auth_router)`; register a `DomainError` exception handler (reuse `easybiz.core.errors`). `auth.py`: `login` (`auth=None`, `throttle=[AnonRateThrottle(settings.EASYBIZ_PLATFORM_LOGIN_RATE)]`) — authenticate the global `User` by email+password (active + `is_platform_admin`), else 401 `Invalid credentials`; return a platform token. `me` (`auth=platform_auth`) → `{id,email}`. `types.py`: `PlatformLoginIn`, `PlatformTokenOut`, `PlatformMeOut`. `urls_public.py`: `path("api/platform/", platform_api.urls)` (keep `/health`). conftest: `admin` fixture + `plat_*` helpers.
  - Note (P-throttle): throttling uses Django's default `LocMemCache`; if a test needs to exhaust the limit deterministically, set a low rate via `settings`/override in that test.

- [ ] **Step 4: Run green; Step 5: full suite (new API mounted) + gate + commit** `git commit -m "Add platform API scaffold, auth endpoints, and public-host docs"`.

---

### Task 4: Tenant read endpoints — overview, list, detail (+ serialisation)

**Files:**
- Create: `easybiz/core/platform_api/tenants.py`, add to `platform_api/types.py`; Modify: `platform_api/__init__.py` (mount `/` tenants router)
- Test: `tests/test_platform_tenants_read.py`

**Interfaces:**
- Produces: `GET /overview`, `GET /tenants?q=&is_active=&limit=&offset=`, `GET /tenants/{slug}`; `TenantOut` = `{slug,name,schema_name,is_active,created_at,domains[{domain,is_primary}],modules[{module,status,installed_version}],member_count}`; `OverviewOut`, `TenantListOut{count,items[]}`.
- Consumes: `Tenant`/`Domain`/`TenantModule`/`Membership` models, `state`/`registry`.

- [ ] **Step 1: Failing tests** (use the `admin`+`plat` helpers and `provision` to create 1–2 tenants):
  - `test_list_excludes_platform_tenant_and_paginates` — `public` never appears; `count`/`items`; `limit` honoured (cap 200).
  - `test_search_by_slug_or_name` — `?q=` filters; `?is_active=` filters.
  - `test_detail_returns_domains_modules_member_count` — a provisioned tenant's `TenantOut` shape.
  - `test_overview_counts` — totals/active/suspended/admins/modules_installed.
  - `test_detail_unknown_slug_404`.

- [ ] **Step 2: Run — expect fail.**

- [ ] **Step 3: Implement** a `_tenant_view(tenant)` serialiser (domains from `Domain`, modules from `TenantModule`, `member_count` from `Membership`), the three read handlers (all `auth=platform_auth`), excluding `get_public_schema_name()` from the list, clamping `limit` to `[0,200]`, and `q` matching slug/name (case-insensitive).

- [ ] **Step 4: Run green; Step 5: gate + commit** `git commit -m "Add platform tenant read endpoints"`.

---

### Task 5: Tenant write endpoints — create, rename, suspend/resume, delete

**Files:**
- Modify: `easybiz/core/platform_api/tenants.py`, `platform_api/types.py`
- Test: `tests/test_platform_tenants_write.py`

**Interfaces:**
- Produces: `POST /tenants`, `PATCH /tenants/{slug}`, `POST /tenants/{slug}/suspend|resume`, `DELETE /tenants/{slug}?confirm_slug=`; `TenantCreateIn`, `TenantRenameIn`. Each mutation calls the matching kernel service + `record_platform`.
- Consumes: `provisioning.provision_tenant`, `tenants.suspend/resume/delete_tenant`, `tenants.validate_new_tenant` errors.

- [ ] **Step 1: Failing tests:**
  - `test_create_tenant_with_module_end_to_end` — 201 `TenantOut`; schema exists; module enabled; owner can then log in on the tenant host; a `tenant.created` platform-audit row.
  - `test_create_conflicts_and_validation` — duplicate slug/domain → 409; bad/reserved slug, bad domain, missing/weak owner password → 422; unknown module → 422 and **nothing created**.
  - `test_existing_person_owns_another_tenant_without_password` — reusing an existing email needs no password.
  - `test_create_rolls_back_on_failure` — force a mid-create failure (e.g. monkeypatch `enable_module` to raise) → no tenant row, no schema, no domain (I14).
  - `test_rename`, `test_suspend_blocks_then_resume_restores` — after suspend: tenant login 403, tenant `/api/auth/me` with a pre-suspension token 403, `/api/docs` 403; resume restores; double suspend/resume → 409.
  - `test_delete_requires_suspension_and_confirmation` — not suspended → 409; wrong/missing `confirm_slug` → 422; suspended + correct → 204, schema dropped, owner user still exists.

- [ ] **Step 2: Run — expect fail.**

- [ ] **Step 3: Implement.** `create`: map `validate_new_tenant`/provisioning errors to 409/422 (prefer the central `DomainError` handler if those raise `DomainError` subclasses; otherwise catch the specific exceptions and map), call `provision_tenant(actor_id=request.auth.id, …)`, `record_platform("tenant.created", target=slug, detail={modules})`, return 201 `_tenant_view`. `rename`→`tenant.renamed`. `suspend`/`resume`→ `tenants.suspend/resume` (409 already-in-state) + audit. `delete`→ `tenants.delete_tenant(tenant, confirm_slug)` (409 not suspended, 422 bad confirm) + `tenant.deleted` audit, 204.

- [ ] **Step 4: Run green; Step 5: full suite + gate + commit** `git commit -m "Add platform tenant create/rename/suspend/resume/delete"`.

---

### Task 6: Tenant domain endpoints

**Files:**
- Modify: `easybiz/core/platform_api/tenants.py`, `platform_api/types.py`
- Test: `tests/test_platform_domains.py`

**Interfaces:**
- Produces: `POST /tenants/{slug}/domains`, `DELETE /tenants/{slug}/domains/{domain}`; `DomainIn{domain, is_primary?}`. Calls `tenants.add_domain`/`remove_domain` + `record_platform` (`tenant.domain_added`/`removed`).

- [ ] **Step 1: Failing tests:** add a domain (normalised to lowercase, no scheme/port); duplicate → 409; invalid → 422; `is_primary` switches the primary; the new host actually serves the tenant API (login via the new domain); remove a non-primary; removing the last domain → 409; removing the primary promotes another; removing a domain not on the tenant → 422.

- [ ] **Step 2–3:** run fail; implement the two handlers mapping `add_domain`/`remove_domain` errors (409/422) and returning `_tenant_view`.

- [ ] **Step 4–5:** green; gate + commit `git commit -m "Add platform tenant domain endpoints"`.

---

### Task 7: Module endpoints — per-tenant toggles + catalog + sync/upgrade

**Files:**
- Create: `easybiz/core/platform_api/modules.py`, add to `platform_api/types.py`; Modify: `platform_api/__init__.py`
- Test: `tests/test_platform_modules.py`

**Interfaces:**
- Produces: `POST /tenants/{slug}/modules/{id}/enable|disable`, `DELETE /tenants/{slug}/modules/{id}/data?confirm=true`, `GET /modules`, `GET /modules/{id}`, `POST /modules/sync`, `POST /modules/upgrade`; `ModuleCatalogOut` per §7.2 (`{id,name,code_version,catalog_version,state,requires[],optional[],provides[],publishes[],subscribes[],permissions[],tenants_enabled,tenants_disabled}`, `state ∈ installed|not_installed|upgrade_pending|missing_code`).
- Consumes: `lifecycle.enable_module/disable_module/remove_module_data/sync_catalog/upgrade_modules`, `registry`, catalog `Module`/`TenantModule`.

- [ ] **Step 1: Failing tests:**
  - `test_enable_disable_remove_from_platform` — toggles reflect in the tenant's `TenantOut.modules`; audited (`tenant.module_enabled`/`disabled`/`data_removed`).
  - `test_module_catalog_and_counts` — `GET /modules` shape incl. `tenants_enabled`/`tenants_disabled`; `state` correct; `GET /modules/{id}` 404 for unknown.
  - `test_sync_and_upgrade` — `POST /modules/sync` refreshes catalog (audited `modules.synced`); `POST /modules/upgrade` runs and is audited `modules.upgraded`.
  - `test_fixed_module_routes_resolve_before_param` (**P8**) — `POST /modules/sync` hits sync, not `/modules/{id="sync"}`.

- [ ] **Step 2: Run — expect fail.**

- [ ] **Step 3: Implement.** `modules.py` with the catalog serialiser (`code_version` from the on-disk manifest via `registry`, `catalog_version` from the `Module` row, `state` derived, `tenants_enabled`/`disabled` counted from `TenantModule`). **Register `/modules/sync` and `/modules/upgrade` before `/modules/{id}`** (P8). Per-tenant toggles resolve the tenant by slug then call lifecycle with `actor_id=request.auth.id` and `record_platform`.

- [ ] **Step 4: Run green; Step 5: gate + commit** `git commit -m "Add platform module toggle, catalog, sync and upgrade endpoints"`.

---

### Task 8: Admin management + audit list + README + close

**Files:**
- Create: `easybiz/core/platform_api/admins.py`, add to `platform_api/types.py`; Modify: `platform_api/__init__.py`, `README.md`
- Test: `tests/test_platform_admins.py`, `tests/test_platform_audit_api.py`

**Interfaces:**
- Produces: `GET /admins`, `POST /admins`, `DELETE /admins/{id}`, `GET /audit?action=&target=&limit=`; `AdminIn{email,password?,name?}`, `AdminOut`, `PlatformAuditOut`.
- Consumes: `User`, `record_platform`, `PlatformAuditLog`.

- [ ] **Step 1: Failing tests:**
  - `test_add_admin_new_and_promote_existing` — new account needs a password (422 without; 422 weak); promoting an existing user needs none; audited `admin.added`.
  - `test_remove_admin_guards` — removing yourself → 409; removing the last admin → 409; unknown id → 404; a valid removal demotes (audited `admin.removed`).
  - `test_audit_list_filters_and_order` — `GET /audit` returns `{at,actor_email,action,target,detail}` newest-first, filterable by `action`/`target`, `limit` capped; the earlier tasks' actions appear in order.

- [ ] **Step 2: Run — expect fail.**

- [ ] **Step 3: Implement** `admins.py` (list active platform admins; add = create-or-promote with the password rule; remove = demote with self/last guards) + the `/audit` handler; each mutation records `admin.added`/`admin.removed`.

- [ ] **Step 4: README** — Status: **M7 complete** (platform admin API on the public host: tenants, domains, per-tenant modules, catalog sync/upgrade, platform admins, audit; `create_platform_admin`; platform docs at `/api/platform/docs`). Add `create_platform_admin` and the platform host to the commands/usage sections; note `scripts/` could grow a platform bootstrap later.

- [ ] **Step 5: Full gate** — `uv run pytest && uv run ruff check . && uv run ruff format --check . && uv run mypy easybiz config && uv run manage.py makemigrations --check --dry-run`.

- [ ] **Step 6: Commit** `git commit -m "Add platform admin management and audit endpoints; document M7"`.

---

## M7 Definition of Done

- [ ] Platform API served only on the public host at `/api/platform/*` with docs at `/api/platform/docs`; absent (404) on tenant hosts; `TenantJWTAuth` returns 401 on the public host.
- [ ] `PlatformJWTAuth` accepts only `scope="platform"` tokens for an active `is_platform_admin` user (read live → demotion immediate); tenant and platform tokens are not interchangeable (I9). Platform login throttled (429).
- [ ] Tenants: overview, list (search/filter/paginate, platform tenant hidden), detail, create (validation/409/422, all-or-nothing rollback I14), rename, suspend/resume (suspend blocks tenant login+API+docs), delete (suspended + `confirm_slug`, schema dropped, users kept).
- [ ] Domains: add (normalise, 409 dup, 422 invalid, primary switch, host then serves the tenant), remove (409 last, 422 not-a-domain, primary promotion).
- [ ] Modules: per-tenant enable/disable/remove-data from the platform; catalog list/detail with counts and `state`; `sync`/`upgrade` (fixed routes before `/{id}`, P8).
- [ ] Admins: list/add (password rule; promote existing)/remove (self + last-admin guards). `GET /audit` lists `PlatformAuditLog` newest-first, filterable; every mutation audited via `record_platform`.
- [ ] `create_platform_admin` creates or promotes. Full suite green on real Postgres; `ruff`/`ruff format`/`mypy`/`makemigrations --check` clean; commits short, no attribution.
