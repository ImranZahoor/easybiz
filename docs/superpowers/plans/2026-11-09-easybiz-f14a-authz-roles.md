# Easybiz F14a (Authorization v2 — role management, inheritance, guards, caching) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete tenant role administration — full role CRUD (update/delete/clone), user-role assignment endpoints, a grouped assignable-permissions listing — add **role inheritance** (the M3a "flat now, revisit in F14" decision), the authorization **guards** (no privilege escalation, last-owner protection, system-role lock), audit + a `core.role.changed` event on every change, and a **version-counter permission cache**.

**Architecture:** Extends the existing core `iam` subsystem. Per §0.5, core uses `service.py` (not a `commands`/`queries` split): the domain logic lives in `easybiz/core/iam/service.py` (+ a small `iam/cache.py`), and `core_routes.py` handlers stay thin (guard → parse → call service → shape response) with domain errors mapped centrally. Role inheritance is additive (a nullable `parent` self-FK); `permissions_for` resolves a role as the union of its own codes and its ancestors'. ABAC (`iam_policy`, expression evaluator, `authorize()`) and org-scope are **out of scope** (F14b / F3).

**Tech Stack:** Django 6.1 + django-tenants, django-ninja, PostgreSQL 16, Django cache (LocMemCache in dev), pytest on real Postgres; `uv`.

**Spec:** `ERP-CORE-SPEC.md` §17 / F14 (role management, inheritance decision, guards, caching). Invariants I2 (reference users by UUID value), I10 (audit). This plan is **F14a** (slice): role management + inheritance + guards + caching; ABAC + policy tooling + org-scope are F14b.

## Current state (verified)

- `iam/models.py`: `Role(id, name unique, description, is_system, created_at)`, `RolePermission(role, permission)`, `UserRole(user_id UUID value, role)`. No `parent` yet.
- `iam/service.py`: `permissions_for(user_id)` (union of the user's roles' codes), `has_permission(perms, code)` (`*`/exact/`module.*`), `assignable_permissions(tenant)`, `role_permissions(role)`, `create_role(tenant, name, permissions, description)` (rejects `*`/unknown/dup via `RoleError`), `ensure_roles_exist`, `set_user_roles(user_id, role_names)`. `RoleError` is a plain `Exception` (core_routes maps it to 422 with a per-handler `try/except`).
- `core_routes.py`: `GET /roles` (list), `POST /roles` (create), `GET/POST/DELETE /users`. No role detail/update/delete/clone, no user-role sub-endpoints, no `GET /permissions`.
- `types.py`: `RoleIn{name,description?,permissions[]}`, `RoleOut{id,name,description,is_system,permissions[]}`, `UserOut{id,email,roles[]}`.
- `events.publish(name, payload, producer="core")`; `audit.record(actor_id, action, entity, entity_id, before, after)`; central `@api.exception_handler(DomainError)` on the tenant NinjaAPI; `_reset_cache` autouse test fixture clears the Django cache per test.

## Scope rulings

- **Ruling (RoleError → DomainError):** make `RoleError` subclass `easybiz.core.errors.DomainError` with status 422 (`RoleError(message)` → `super().__init__(message, 422)`), so new thin handlers need no `try/except` and it maps centrally. Existing `core_routes` `except iam.RoleError` still catches it (harmless); a new 409-class guard (last owner) raises `DomainError(msg, 409)` directly. Cost if wrong: revert to per-handler mapping.
- **Ruling (grant guard covers both define and assign):** "nobody can grant a permission they do not hold" applies to *defining* a role's permissions (create/update/clone) **and** to *assigning* a role (giving a user a role whose effective permissions exceed the actor's). `*` holders are exempt. Cost if wrong: an escalation path.
- **Ruling (inheritance = single nullable parent):** chain inheritance via `Role.parent` (self-FK, `on_delete=SET_NULL`); effective codes = union over the role + its ancestors; a cycle is rejected on write. Multi-parent `includes` is deferred. Cost if wrong: migrate to an M2M later (additive).
- **Ruling (cache scope):** the version-counter cache accelerates the hot auth path via `cached_permissions_for`; `permissions_for` stays the uncached source of truth (always fresh for `/me`, guards, tests). Every role/assignment mutation bumps the per-schema `role_version`. Per-request repeat calls are served by the same cache key (a hit). Cost if wrong: a stale-perms window (bounded by the 60s TTL + version bump).

## Global Constraints

- Python 3.13; Django ≥5.2 (6.1); PostgreSQL 16; `uv`; pytest (real Postgres).
- §0.5: core logic in `service.py`; thin handlers; domain errors via `DomainError` + central handler; types in `types.py`; no module docstrings; concise docstrings; imports at top; named predicates past two conditions; **short, plain comments**; `ruff`/`ruff format --check`/`mypy easybiz config` clean; `makemigrations --check` clean; short commits, no attribution.
- I2: `UserRole.user_id` stays a bare UUID value (no cross-schema FK). I10: every role/assignment change writes an audit row (before/after) and publishes `core.role.changed`.
- Inheritance is additive: a role with no `parent` behaves exactly as today.

## Review Focus

- **Define-time escalation:** a manager holding `timesheets.*` but not `core.user.manage` cannot create/update/clone a role that includes `core.user.manage` (422); a `*` holder can. → Task 2.
- **Assign-time escalation:** that manager cannot assign a role whose effective permissions exceed their own (e.g. `owner`/`*`) to any user (422). → Task 3.
- **Last-owner protection:** removing/replacing the `owner` role from the last user who holds it (via `PUT`/`DELETE` user-roles) is refused (409); deleting the `owner` role is refused. → Task 3.
- **System-role lock:** `PATCH` on a system role may change only its description (name/permissions/parent changes 422); `DELETE` of a system role is refused (409). → Task 2.
- **Inheritance correctness:** effective permissions = union over role + ancestors across a multi-level chain; setting a parent that would form a cycle is rejected (422); `has_permission` still honours `module.*`/`*` after inheritance. → Tasks 1, 4.
- **Cache invalidation:** after a role/assignment change, the next auth check reflects it (the `role_version` bump invalidates the cached entry) — no stale grant. → Task 5.
- **Delete-assigned safety:** deleting a role still assigned to users is refused without `?force=true`; with it, the role and its assignments are removed and audited. → Task 2.

---

### Task 1: Role inheritance (model + resolution + cycle guard) + `RoleError` → `DomainError`

**Files:**
- Modify: `easybiz/core/iam/models.py`, `easybiz/core/iam/service.py`; Create: `easybiz/core/iam/migrations/000N_role_parent.py` (generated)
- Test: `tests/test_iam_inheritance.py`

**Interfaces:**
- Produces: `Role.parent` (nullable self-FK); `service.effective_codes(role) -> set[str]` (role + ancestors); `permissions_for(user_id)` now inheritance-aware; `service.would_cycle(role, new_parent) -> bool`; `RoleError(DomainError, status=422)`.

- [ ] **Step 1: Write failing tests** — `tests/test_iam_inheritance.py` (use `synced`, `db_tenant`, `tenant_context`):

```python
def test_permissions_union_over_ancestors(synced, db_tenant):
    from django_tenants.utils import tenant_context
    from easybiz.core.iam import service as iam
    from easybiz.core.iam.models import Role, RolePermission, UserRole

    with tenant_context(db_tenant):
        base = Role.objects.create(name="base")
        RolePermission.objects.create(role=base, permission="core.audit.read")
        mgr = Role.objects.create(name="mgr", parent=base)
        RolePermission.objects.create(role=mgr, permission="core.user.read")
        UserRole.objects.create(user_id="11111111-1111-1111-1111-111111111111", role=mgr)
        perms = iam.permissions_for("11111111-1111-1111-1111-111111111111")
        assert {"core.audit.read", "core.user.read"} <= perms  # own + inherited


def test_would_cycle_rejects_self_or_descendant(synced, db_tenant):
    from django_tenants.utils import tenant_context
    from easybiz.core.iam import service as iam
    from easybiz.core.iam.models import Role

    with tenant_context(db_tenant):
        a = Role.objects.create(name="a")
        b = Role.objects.create(name="b", parent=a)
        assert iam.would_cycle(a, a) is True  # self
        assert iam.would_cycle(a, b) is True  # b descends from a -> would loop
        assert iam.would_cycle(b, a) is False
```

- [ ] **Step 2: Run — expect fail** (no `parent`/`would_cycle`).

- [ ] **Step 3: Implement.** `models.py`: `parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="children")`. `service.py`: make `RoleError(DomainError)` (`__init__(self, message): super().__init__(message, 422)`; import `DomainError`). Add `_ancestors(role)` (walk `parent`, bounded, stop on repeat), `effective_codes(role)` (union of role's + ancestors' `RolePermission` codes), and rewrite `permissions_for(user_id)` to union `effective_codes` over the user's roles. Add `would_cycle(role, new_parent)` (True if `new_parent is role` or `role` is in `new_parent`'s ancestor set).

- [ ] **Step 4: Migration** `uv run manage.py makemigrations iam`; **Step 5:** run tests green; **Step 6:** gate + commit `git commit -m "Add role inheritance and make RoleError a DomainError"`.

---

### Task 2: Role write — update / delete / clone, with guards + audit + event

**Files:**
- Modify: `easybiz/core/iam/service.py`, `easybiz/core/api/core_routes.py`, `easybiz/core/api/types.py`
- Test: `tests/test_core_roles_write_api.py`

**Interfaces:**
- Produces service fns (all take the actor's effective perm set for the escalation guard): `update_role(tenant, role_id, *, name, description, permissions, parent_name, actor_perms) -> Role`; `delete_role(role_id, force) -> None`; `clone_role(tenant, role_id, new_name, actor_perms) -> Role`. Endpoints: `GET /roles/{id}`, `PATCH /roles/{id}`, `DELETE /roles/{id}?force=`, `POST /roles/{id}/clone`. Types: `RoleUpdateIn{name?, description?, permissions?, parent?}`, `RoleCloneIn{name}`.

- [ ] **Step 1: Failing tests** covering: update name/description/permissions on a normal role; **escalation** — an actor without `core.user.manage` cannot add it to a role (422), a `*` actor can; **system lock** — PATCH a system role changing permissions → 422, changing only description → 200; set `parent` to form a **cycle** → 422; **delete** a system role → 409; delete an assigned role without `force` → 409, with `?force=true` → 204 (assignments gone); clone duplicates permissions (+parent) under a new name (dup name → 422). Each asserts an audit row and that `core.role.changed` was published (`OutboxEvent.objects.filter(name="core.role.changed")`).

- [ ] **Step 2: Run — expect fail.**

- [ ] **Step 3: Implement.** Service: the escalation guard `_assert_grantable(perms, actor_perms)` — every requested code must be covered by `has_permission(actor_perms, code)` unless `*` in `actor_perms`, else `RoleError`. `update_role`: load or 404 (`DomainError(404)`); if `is_system`, only `description` may change else `RoleError`; validate perms assignable + grantable; set `parent` by name with `would_cycle` guard; replace `RolePermission` rows; `audit.record(... before/after ...)`; `events.publish("core.role.changed", {"role": name}, producer="core")`. `delete_role`: 409 if `is_system`; 409 if assigned and not `force`; else delete (+audit+event). `clone_role`: copy perms (+parent) to a new name (grant-guarded; dup → `RoleError`). Handlers in `core_routes.py` stay thin (`perm("core.role.manage")`; read uses `perm("core.role.read")`), passing `iam.permissions_for(request.auth.id)` as `actor_perms`; domain errors map centrally.

- [ ] **Step 4: Run green; Step 5: gate + commit** `git commit -m "Add role update/delete/clone with escalation and system-role guards"`.

---

### Task 3: User-role assignment endpoints + last-owner guard

**Files:**
- Modify: `easybiz/core/iam/service.py`, `easybiz/core/api/core_routes.py`, `easybiz/core/api/types.py`
- Test: `tests/test_core_user_roles_api.py`

**Interfaces:**
- Produces: `set_user_roles(user_id, role_names, actor_perms)` (now grant-guarded + last-owner-guarded), `add_user_role(user_id, role_name, actor_perms)`, `remove_user_role(user_id, role_name)`; `assert_owner_retained(...)`. Endpoints: `PUT /users/{id}/roles` (`{roles[]}`), `POST /users/{id}/roles/{name}`, `DELETE /users/{id}/roles/{name}` (all `core.user.manage`).

- [ ] **Step 1: Failing tests:** assign a role → user's `roles` reflect it; **assign-escalation** — an actor who lacks `*` cannot assign `owner` (whose effective perms include `*`) → 422; **last-owner** — removing/replacing `owner` from the only owner-holder → 409, but fine when another owner exists; add/remove single role idempotent-ish; unknown role → 422; each change audited + `core.role.changed` published.

- [ ] **Step 2: Run — expect fail.**

- [ ] **Step 3: Implement.** Guard helpers: grant-guard an assignment by checking `effective_codes(role) ⊆ actor_perms` (or `*`); `_is_last_owner_removal(user_id, new_role_names)` — true if the user currently holds `owner`, `owner` is not in the new set, and no other active user holds `owner` → `DomainError(409)`. Wire into `set_user_roles`/`remove_user_role`. Update existing callers of `set_user_roles` (provisioning, `core_routes.create_user`) to pass `actor_perms` — for system/bootstrap callers pass a sentinel meaning "unrestricted" (e.g. `{"*"}`) so provisioning is unaffected. Audit + publish on each. Handlers thin.

- [ ] **Step 4: Run green; Step 5: gate + commit** `git commit -m "Add user-role assignment endpoints with escalation and last-owner guards"`.

---

### Task 4: Read endpoints — role detail + grouped permissions

**Files:**
- Modify: `easybiz/core/api/core_routes.py`, `easybiz/core/api/types.py`, `easybiz/core/iam/service.py`
- Test: `tests/test_core_permissions_api.py`

**Interfaces:**
- Produces: `GET /roles/{id}` → `RoleDetailOut{id,name,description,is_system,parent,permissions[],effective_permissions[]}`; `GET /permissions` → `PermissionGroupOut[]` (`{module, permissions:[{code,description}]}`), `core.role.read`. Service: `permission_groups(tenant) -> list[...]`.

- [ ] **Step 1: Failing tests:** `GET /roles/{id}` returns `parent` and `effective_permissions` (own + inherited) distinct from `permissions`; `GET /permissions` groups assignable permissions by module (core group + enabled-module groups) with descriptions; a disabled module's permissions are absent. (Reuse the `_token(provision)` client helper.)

- [ ] **Step 2–3:** run fail; implement `RoleDetailOut`/`PermissionGroupOut`, `service.permission_groups(tenant)` (from `Permission` rows filtered by `assignable_permissions`, grouped by `module_id`/core), the two thin handlers.

- [ ] **Step 4–5:** green; gate + commit `git commit -m "Add role detail and grouped permissions endpoints"`.

---

### Task 5: Versioned permission cache

**Files:**
- Create: `easybiz/core/iam/cache.py`; Modify: `easybiz/core/iam/service.py` (bump on mutations), `easybiz/core/api/security.py` (auth uses the cached path)
- Test: `tests/test_iam_cache.py`

**Interfaces:**
- Produces: `cache.role_version() -> int`, `cache.bump_role_version()`, `cache.cached_permissions_for(user_id) -> set[str]` (Django cache keyed `(schema, user_id, version)`, TTL 60s, delegating to `service.permissions_for`). Every role/assignment mutation in `service.py` calls `bump_role_version()`.

- [ ] **Step 1: Failing tests:** `cached_permissions_for(u)` returns the same as `permissions_for(u)`; after granting a new permission to the user's role, `cached_permissions_for(u)` reflects it on the **next call** (because the mutation bumped the version) — i.e. no stale grant; two different users get independent entries.

- [ ] **Step 2: Run — expect fail.**

- [ ] **Step 3: Implement.** `cache.py`: `role_version()` reads `cache.get_or_set(f"iam:ver:{schema}", 1)`; `bump_role_version()` = `cache.set(key, role_version()+1)` (or `incr` guarded); `cached_permissions_for(user_id)` builds key `iam:perms:{schema}:{user_id}:{version}`, `cache.get_or_set(key, lambda: service.permissions_for(user_id), 60)`. Call `bump_role_version()` from every mutating service fn (create/update/delete/clone role, set/add/remove user roles). Point `security.TenantJWTAuth._grants` at `cached_permissions_for`. (Schema from `connection.schema_name`.)
  - Note: dev/test cache is LocMemCache (per-process); a shared cache for multi-process correctness is F22. The `_reset_cache` autouse fixture keeps tests isolated.

- [ ] **Step 4: Run green; Step 5: full suite + gate + commit** `git commit -m "Add versioned permission cache with invalidation"`.

---

### Task 6: Docs + event catalogue + close

**Files:** Modify: `README.md`, `ERP-CORE-SPEC.md` (Appendix D event catalogue: add `core.role.changed`)

- [ ] **Step 1:** README Status — **F14a complete** (role CRUD + clone, user-role assignment, grouped permissions, role inheritance, escalation/last-owner/system-role guards, `core.role.changed`, versioned permission cache). Note ABAC + org-scope remain F14b/F3.
- [ ] **Step 2:** add `core.role.changed` to the spec's event catalogue (Appendix D).
- [ ] **Step 3: Full gate** — `uv run pytest && uv run ruff check . && uv run ruff format --check . && uv run mypy easybiz config && uv run manage.py makemigrations --check --dry-run`.
- [ ] **Step 4: Commit** `git commit -m "Document F14a authorization v2 (roles)"`.

---

## F14a Definition of Done

- [ ] Role CRUD (`GET`/`PATCH`/`DELETE`/`clone`) + user-role assignment (`PUT`/`POST`/`DELETE`) + `GET /permissions` (grouped) + `GET /roles/{id}` (with parent + effective permissions).
- [ ] Role inheritance: effective permissions = union over role + ancestors; cycles rejected; flat roles unchanged.
- [ ] Guards: no define-time or assign-time privilege escalation (`*` exempt); last `owner` holder cannot be demoted and the `owner` role cannot be deleted; system roles locked except description; delete-assigned needs `?force=true`.
- [ ] Every role/assignment change is audited (before/after) and publishes `core.role.changed`.
- [ ] Versioned permission cache accelerates the auth path and invalidates on any change (no stale grant).
- [ ] Full suite green on real Postgres; ruff/format/mypy/makemigrations clean; commits short, no attribution.
