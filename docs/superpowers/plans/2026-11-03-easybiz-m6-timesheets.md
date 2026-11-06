# Easybiz M6 (Timesheets Reference Module) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Flesh out the `timesheets` module skeleton into the full §8 reference module — models, migrations, permissions/roles/menu, `/api/timesheets` endpoints, the approved/rejected events + `core.membership.removed` handler, and the `AttendanceProvider` capability — proving the module contract end to end.

**Architecture:** `timesheets` is a per-tenant module (tables only when enabled, gated by the M3 migration router). It declares permissions/roles/menu/events in its manifest, exposes a Ninja `Router` mounted under `/api/timesheets` (via a new generic module-router auto-mount, since Timesheets is the first module with an API), publishes outbox events through `events.publish` inside the business transaction, subscribes to `core.membership.removed`, and registers `AttendanceProvider` via `capabilities.register` at import of `providers.py`.

**Tech Stack:** Django 6.1 + django-tenants, django-ninja (Router, `perm()` guard, `Status`, `HttpError`), PostgreSQL 16, pytest; `uv`.

**Spec:** `ERP-CORE-SPEC.md` — §8 (Timesheets in full), §4.2 (event payloads), §5.8 (capabilities), §5.9 (events), §6 (`perm()` auth), §9 (test infra), §10 (`test_timesheets_and_events.py` = 11 tests; `test_module_lifecycle.py`), M6 (§11), invariants I1/I2 (no cross-module imports or FKs; reference users by UUID value), I6 (events), I7 (capability gated by enablement).

## Current state (verified against the tree)

- `easybiz/modules/timesheets/` exists as a registered-but-empty skeleton: `apps.py` (label `timesheets`, name `easybiz.modules.timesheets`), a minimal `manifest.json` (empty permissions/roles/events/menu), empty `models.py`, empty `migrations/__init__.py`. It is already in `EASYBIZ_MODULE_PACKAGES` (settings default + `.env`) and loads cleanly today.
- Capability machinery exists: `easybiz/core/contracts.py` already declares `AttendanceProvider.approved_hours(user_id: UUID, start: date, end: date) -> Decimal`; `easybiz/core/kernel/capabilities.py` has `register(contract, impl, module_id)` / `get(contract, optional=False)` (gated by `state.is_enabled(connection.tenant, module_id)`) + `CapabilityUnavailable`.
- Events: `easybiz/core/events/service.py` has `publish(name, payload, producer, version)` (rejects undeclared module events) and `dispatch_pending`. The `demo` module already proves idempotency/parking/retry/dead-letter end to end (M5).
- Routers: `config/urls.py` mounts only `easybiz.core.api.api` (`/api/auth`, `/api/core`). **No module router is mounted anywhere.** `ModuleGateMiddleware` already returns 404 for `/api/<module>/...` when the module is not enabled for the tenant (regex `^/api/([a-z][a-z0-9_]*)(/|$)`).
- Test infra (actual, not the idealized §9 list): `tests/conftest.py` provides `synced` (runs `sync_catalog`), `db_tenant` (schema `t_state`, core tenant apps only), `provision` (`provision(slug=, modules=())` → full tenant + owner with role `owner`/`*`), `tables_in`. API tests use `django.test.Client` with `HTTP_HOST="<slug>.localhost"` + `HTTP_AUTHORIZATION="Bearer <token>"`; the login helper pattern is `POST /api/auth/login {email, password}` → `access_token`. `encode_tenant_token(user_id, schema_name)` mints a token directly.

## Scope rulings

- **Ruling (test file):** the spec catalogues 11 behaviours under `test_timesheets_and_events.py`. Four of them — undeclared-event rejection, inbox idempotency, parked-then-replayed, retry-backoff-then-dead — are generic event-machinery properties already proven against `demo` in M5 (`test_events_*.py`). M6 re-proves the ones that are *timesheets-specific and cheap*: the `drop_draft_entries` handler's idempotency (inbox) and the approved-event-in-transaction. The purely generic engine properties (parked/replay, retry/dead, undeclared-publish) are NOT duplicated with a timesheets skin — they are M5's and would test the same code path. This is noted so a reviewer counting "11" sees the intent. Cost if wrong: add thin timesheets-flavored duplicates later.
- **Ruling (router mounting):** auto-mount belongs in M6 (Timesheets is the first module needing it) and is generic: iterate `registry.module_ids()`, import each `easybiz.modules.<id>.api` if present, `api.add_router(f"/{id}", module.router)`. Per-tenant visibility is already handled by `ModuleGateMiddleware`; mounting is install-wide. Cost if wrong: isolated to Task 2.
- **Ruling (`user_id` by value, I2):** `timesheets_entry.user_id` is a bare `UUIDField` (no FK to the shared `users_user`); the API fills it from `request.auth.id`. Cross-schema FKs are forbidden (I2).

## Global Constraints

- Python 3.13; Django ≥5.2 (6.1); PostgreSQL 16; `uv`; pytest (DB required, real Postgres).
- §0.5: types in `types.py` (not logic files); no module docstrings; one concise docstring per public class/function; all imports at top; named predicates past two conditions; DRY/SOLID where they fit; `ruff check`/`ruff format --check`/`mypy easybiz config` clean; `makemigrations --check --dry-run` clean; short commits, **no attribution/co-author lines**.
- Naming (§0.5): permissions `<module>.<resource>.<action>`; events `<module>.<entity>.<past-verb>`; tables prefixed `timesheets_`.
- Module values from §8: app label `timesheets`, version `0.1.0`, no dependencies. Project `code` stored uppercase, unique. Entry `hours` decimal(4,2) with DB check `timesheets_hours_range`: `0 < hours <= 24` (Django 6 `condition=`). Entry `status` in `draft|submitted|approved|rejected`. Event payload for approved/rejected: `{entry_id, user_id, project_id, work_date, hours}` with **hours as string**.

## Review Focus

- **Self-approval / self-review (403):** an approver approving or rejecting their *own* submitted entry must get 403, even though they hold `entry.approve`. → Task 5.
- **Visibility leak:** a user with only `entry.read` must never see another user's entries via `GET /entries` (and `user_id` filter is ignored for them); an approver may filter by `user_id`. → Task 4.
- **Capability gated by enablement (I7):** `AttendanceProvider.approved_hours` counts only `approved` entries in `[start, end]`; `capabilities.get(AttendanceProvider)` returns the impl only while timesheets is enabled, else `None` (optional) / raises `CapabilityUnavailable`. → Task 7.
- **Event in the same transaction (I6):** if the audit/publish inside approve fails, the status change rolls back (no approved entry without its event, no event without the approval). → Task 5.
- **Removed user's drafts only:** the `core.membership.removed` handler deletes that user's `draft` entries but keeps `submitted`/`approved`/`rejected`; and is idempotent if the event is redelivered (inbox). → Task 6.
- **Hours bounds at the DB and API:** `hours` of `0`, negative, or `> 24` is rejected (422 at API; the DB check is the backstop). → Task 4.

---

### Task 1: Models + migration

**Files:**
- Modify: `easybiz/modules/timesheets/models.py`
- Create: `easybiz/modules/timesheets/migrations/0001_initial.py` (generated)
- Test: `tests/test_timesheets_models.py`

**Interfaces:**
- Produces: `Project(id, code, name, is_active, created_at)` with `code` unique; `Entry(id, user_id, project→Project PROTECT, work_date, hours, note, status, reviewed_by, review_note, created_at)`; `Entry` status constants `DRAFT/SUBMITTED/APPROVED/REJECTED`; DB constraint `timesheets_hours_range`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_timesheets_models.py
import datetime
from decimal import Decimal

import pytest
from django.db import IntegrityError
from django_tenants.utils import tenant_context

from easybiz.core.kernel import lifecycle


def _enable(db_tenant):
    lifecycle.enable_module(db_tenant, "timesheets")


def test_project_and_entry_persist(synced, db_tenant):
    _enable(db_tenant)
    from easybiz.modules.timesheets.models import Entry, Project

    with tenant_context(db_tenant):
        p = Project.objects.create(code="ALPHA", name="Alpha")
        e = Entry.objects.create(
            user_id="11111111-1111-1111-1111-111111111111",
            project=p,
            work_date=datetime.date(2026, 11, 3),
            hours=Decimal("8.00"),
            status=Entry.DRAFT,
        )
        assert e.status == "draft" and p.code == "ALPHA"


def test_hours_range_constraint(synced, db_tenant):
    _enable(db_tenant)
    from easybiz.modules.timesheets.models import Entry, Project

    with tenant_context(db_tenant):
        p = Project.objects.create(code="BETA", name="Beta")
        with pytest.raises(IntegrityError):
            Entry.objects.create(
                user_id="22222222-2222-2222-2222-222222222222",
                project=p,
                work_date=datetime.date(2026, 11, 3),
                hours=Decimal("25.00"),
                status=Entry.DRAFT,
            )
```

- [ ] **Step 2: Run — expect fail** (`Project`/`Entry` undefined). `uv run pytest tests/test_timesheets_models.py -q`

- [ ] **Step 3: Implement the models** in `models.py` per §8.1. `Project`: `id` UUID pk, `code` CharField(30, unique=True), `name` CharField(200), `is_active` BooleanField(default=True), `created_at` auto_now_add. `Entry`: `id` UUID pk, `user_id` UUIDField(db_index=True), `project` FK(Project, on_delete=PROTECT), `work_date` DateField(db_index=True), `hours` DecimalField(max_digits=4, decimal_places=2), `note` CharField(300, blank=True, default=""), `status` CharField(10, db_index=True, default=DRAFT) with status constants, `reviewed_by` UUIDField(null=True, blank=True), `review_note` CharField(300, blank=True, default=""), `created_at` auto_now_add. Add `Meta.constraints = [CheckConstraint(condition=Q(hours__gt=0) & Q(hours__lte=24), name="timesheets_hours_range")]`. (`code` is uppercased by the API layer, not the model.)

- [ ] **Step 4: Generate the migration** `uv run manage.py makemigrations timesheets`. Expected: creates `0001_initial.py` with both models + the constraint.

- [ ] **Step 5: Run tests — expect pass.** `uv run pytest tests/test_timesheets_models.py -q`

- [ ] **Step 6: Gate + commit**

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy easybiz config && uv run manage.py makemigrations --check --dry-run
git add easybiz/modules/timesheets/models.py easybiz/modules/timesheets/migrations/0001_initial.py tests/test_timesheets_models.py
git commit -m "Add Timesheets models and migration"
```

---

### Task 2: Manifest + module-router auto-mount

**Files:**
- Modify: `easybiz/modules/timesheets/manifest.json`
- Create: `easybiz/modules/timesheets/api.py` (empty `Router` for now — fleshed out in Tasks 3–5)
- Modify: `easybiz/core/api/__init__.py` (mount module routers)
- Test: `tests/test_timesheets_manifest.py`, `tests/test_module_router_mount.py`

**Interfaces:**
- Produces: `easybiz.modules.timesheets.api.router` (ninja `Router`); each installed module's router mounted at `/api/<id>`.
- Consumes: `registry.module_ids()` (M2), `ModuleGateMiddleware` (M4) for per-tenant gating.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_timesheets_manifest.py
from easybiz.core.kernel.registry import registry


def test_manifest_declares_permissions_roles_events_menu():
    m = registry.manifest("timesheets")
    codes = {c for c, _ in m.permissions}
    assert codes == {
        "timesheets.project.read",
        "timesheets.project.manage",
        "timesheets.entry.create",
        "timesheets.entry.read",
        "timesheets.entry.approve",
    }
    assert set(m.publishes) == {"timesheets.entry.approved", "timesheets.entry.rejected"}
    role_names = {r["name"] for r in m.roles}
    assert {"timesheet_user", "timesheet_approver"} <= role_names
```

```python
# tests/test_module_router_mount.py
from easybiz.core.api import api


def test_timesheets_router_is_mounted():
    paths = {str(p.pattern) for p in api.urls[0]}  # mounted sub-routers
    assert any("timesheets" in p for p in paths)
```

- [ ] **Step 2: Run — expect fail** (manifest empty; router not mounted). The manifest test fails on `permissions`; the mount test fails because `api.py` has no router / isn't mounted. Note: if `test_module_router_mount` is awkward against `api.urls`, assert instead that an enabled tenant gets non-404 on `GET /api/timesheets/projects` and a fresh (no-timesheets) tenant gets 404 — see Task 4; keep whichever is reliable and drop the other in a Ruling.

- [ ] **Step 3: Fill the manifest** per §8.2: the five permissions (with descriptions), roles `timesheet_user` (`project.read`, `entry.create`, `entry.read`) and `timesheet_approver` (all five), `events.publishes` `["timesheets.entry.approved","timesheets.entry.rejected"]`, menu `[{"label":"Timesheets","path":"/timesheets","permission":"timesheets.entry.read"},{"label":"Projects","path":"/timesheets/projects","permission":"timesheets.project.manage"}]`. **Leave `events.subscribes` empty here** — it is added in Task 6 together with the handler, because `registry.import_module_code()` fails `manage.py check` if a declared subscription has no registered handler. (Match the menu field shape the existing `demo`/core manifests use — check `manifest.py` `menu` parsing.)

- [ ] **Step 4: Create `api.py`** with `from ninja import Router` and `router = Router()` (handlers added in later tasks).

- [ ] **Step 5: Mount module routers** in `easybiz/core/api/__init__.py`: after the core routers, iterate `registry.module_ids()`; for each, import `easybiz.modules.<id>.api` if it exists (`importlib.util.find_spec`), and if the module defines `router`, call `api.add_router(f"/{id}", module.router)`. Registry is already loaded by `KernelConfig.ready()` before `config/urls.py` imports `api`.

- [ ] **Step 6: Run both tests + startup check — expect pass.** `uv run manage.py check && uv run pytest tests/test_timesheets_manifest.py tests/test_module_router_mount.py -q`

- [ ] **Step 7: Gate + commit** (ruff/format/mypy; `makemigrations --check`). `git commit -m "Declare Timesheets manifest and auto-mount module API routers"`

---

### Task 3: Projects API (`GET`/`POST /projects`)

**Files:**
- Modify: `easybiz/modules/timesheets/api.py`
- Create: `easybiz/modules/timesheets/types.py`
- Test: `tests/test_timesheets_projects_api.py`

**Interfaces:**
- Consumes: `perm()` from `easybiz.core.api.security`; `audit.record` from `easybiz.core.audit.service`.
- Produces: `ProjectIn(code, name)`, `ProjectOut(id, code, name, is_active)`; `GET /projects`, `POST /projects`.

- [ ] **Step 1: Write failing tests** (reuse the Client pattern; provision a tenant with `modules=("timesheets",)`, login owner for the token).

```python
# tests/test_timesheets_projects_api.py
from django.test import Client


def _token(provision, slug="ts1"):
    provision(slug=slug, modules=("timesheets",))
    r = Client().post(
        "/api/auth/login",
        data={"email": f"owner@{slug}.test", "password": "change-me-now"},
        content_type="application/json",
        HTTP_HOST=f"{slug}.localhost",
    )
    return r.json()["access_token"]


def _post(path, token, body, slug="ts1"):
    return Client().post(
        path, data=body, content_type="application/json",
        HTTP_HOST=f"{slug}.localhost", HTTP_AUTHORIZATION=f"Bearer {token}",
    )


def _get(path, token, slug="ts1"):
    return Client().get(path, HTTP_HOST=f"{slug}.localhost", HTTP_AUTHORIZATION=f"Bearer {token}")


def test_create_project_uppercases_code(synced, provision):
    token = _token(provision)
    r = _post("/api/timesheets/projects", token, {"code": "alpha", "name": "Alpha"})
    assert r.status_code == 201 and r.json()["code"] == "ALPHA"


def test_duplicate_code_409(synced, provision):
    token = _token(provision)
    _post("/api/timesheets/projects", token, {"code": "dup", "name": "A"})
    assert _post("/api/timesheets/projects", token, {"code": "DUP", "name": "B"}).status_code == 409


def test_projects_listed_ordered_by_code(synced, provision):
    token = _token(provision)
    _post("/api/timesheets/projects", token, {"code": "zeta", "name": "Z"})
    _post("/api/timesheets/projects", token, {"code": "amp", "name": "A"})
    codes = [p["code"] for p in _get("/api/timesheets/projects", token).json()]
    assert codes == sorted(codes)
```

- [ ] **Step 2: Run — expect fail** (404/no handler).

- [ ] **Step 3: Implement types + handlers.** `types.py`: `ProjectIn`/`ProjectOut` (ninja Schema). `api.py`: `GET /projects` (`perm("timesheets.project.read")`, ordered by `code`) → `list[ProjectOut]`; `POST /projects` (`perm("timesheets.project.manage")`) uppercases `data.code`, rejects duplicate with `HttpError(409,...)` (catch `IntegrityError` or pre-check), `audit.record(request.auth.id, "timesheets.project.created", entity="project", entity_id=str(p.id))`, returns `Status(201, ProjectOut(...))`.

- [ ] **Step 4: Run — expect pass.**

- [ ] **Step 5: Gate + commit.** `git commit -m "Add Timesheets projects API"`

---

### Task 4: Entries API — create, list (visibility), submit

**Files:**
- Modify: `easybiz/modules/timesheets/api.py`, `easybiz/modules/timesheets/types.py`
- Test: `tests/test_timesheets_entries_api.py`

**Interfaces:**
- Consumes: Task 1 models, Task 3 token/client helpers (duplicate the small `_token/_post/_get` helpers or import from the projects test module).
- Produces: `EntryIn(project_id, work_date, hours, note?)`, `EntryOut(id, user_id, project_id, work_date, hours, note, status)`; `POST /entries`, `GET /entries?status=&user_id=`, `POST /entries/{id}/submit`. Helper `_add_user(tenant, email, roles)` that creates a user with given roles and returns `(user, token)` for multi-user tests.

- [ ] **Step 1: Write failing tests** covering: create draft for caller (project must exist and be active → 404 otherwise); `hours` in `(0,24]` else 422 (test `0`, `25`); list shows only own for an `entry.read`-only user; an `entry.approve` user sees all and may filter `?user_id=`; submit own `draft`→`submitted`, submit someone else's → 404, submit an `approved` entry → 409. Use a second user via a helper:

```python
def _add_user(tenant, email, roles):
    from django_tenants.utils import tenant_context
    from easybiz.core.api.security import encode_tenant_token
    from easybiz.core.iam import service as iam
    from easybiz.core.users import service as users
    with tenant_context(tenant):
        u = users.create_user(email, tenant, password="change-me-now")
        iam.set_user_roles(u.id, roles)
    return u, encode_tenant_token(u.id, tenant.schema_name)
```
(The `provision` fixture returns the tenant; capture it to pass here. Confirm `iam.set_user_roles` seeds the module roles — they exist after enable via `_seed_roles`.)

- [ ] **Step 2: Run — expect fail.**

- [ ] **Step 3: Implement.** `EntryIn`/`EntryOut` in `types.py`. `POST /entries` (`perm("timesheets.entry.create")`): 404 if project missing/`is_active=False`; 422 if `not (0 < hours <= 24)`; create `draft` with `user_id=request.auth.id`. `GET /entries` (`perm("timesheets.entry.read")`): base queryset filtered by optional `status`; a caller **without** `entry.approve` is forced to their own `user_id` (ignore the query param); a caller **with** `entry.approve` sees all and honours `?user_id=`. Decide "has approve" via `iam.has_permission(iam.permissions_for(request.auth.id), "timesheets.entry.approve")`. `POST /entries/{id}/submit` (`perm("timesheets.entry.create")`): 404 if not the caller's entry; `draft|rejected`→`submitted`, else 409.

- [ ] **Step 4: Run — expect pass.**

- [ ] **Step 5: Gate + commit.** `git commit -m "Add Timesheets entries create/list/submit API"`

---

### Task 5: Approve / reject (+ events in one transaction)

**Files:**
- Modify: `easybiz/modules/timesheets/api.py`, `easybiz/modules/timesheets/types.py`
- Test: `tests/test_timesheets_review_api.py`

**Interfaces:**
- Consumes: `events.publish` (`easybiz.core.events.service`), `audit.record`, Task 4 `_add_user` helper, `OutboxEvent` model (assertions).
- Produces: `POST /entries/{id}/approve`, `POST /entries/{id}/reject` (`RejectIn(reason?)`).

- [ ] **Step 1: Write failing tests:** approver approves a `submitted` entry → `approved`, and an `OutboxEvent` `timesheets.entry.approved` exists with payload `{entry_id,user_id,project_id,work_date,hours}` (hours as string); approving a non-`submitted` entry → 409; approver approving their **own** submitted entry → 403 (self-review); a user without `entry.approve` → 403 (guard); reject sets `rejected` + publishes `timesheets.entry.rejected`; double-approve → 409. Assert the event row via `tenant_context` + `OutboxEvent.objects.filter(name="timesheets.entry.approved")`.

- [ ] **Step 2: Run — expect fail.**

- [ ] **Step 3: Implement.** Both handlers `perm("timesheets.entry.approve")`. Shared predicate: entry must be `submitted` else `HttpError(409,...)`; `entry.user_id == request.auth.id` → `HttpError(403, "cannot review your own time")`. Wrap in `transaction.atomic()`: set status (`approved`/`rejected`), `reviewed_by=request.auth.id`, `review_note=reason` (reject), `audit.record(...)`, then `events.publish("timesheets.entry.approved"|".rejected", {"entry_id":str(e.id),"user_id":str(e.user_id),"project_id":str(e.project_id),"work_date":e.work_date.isoformat(),"hours":str(e.hours)}, producer="timesheets")`.

- [ ] **Step 4: Run — expect pass.**

- [ ] **Step 5: Gate + commit.** `git commit -m "Add Timesheets approve/reject with events"`

---

### Task 6: Membership-removed handler (`drop_draft_entries`)

**Files:**
- Create: `easybiz/modules/timesheets/handlers.py`
- Modify: `easybiz/modules/timesheets/manifest.json` (add `events.subscribes: ["core.membership.removed"]`)
- Test: `tests/test_timesheets_handler.py`

**Interfaces:**
- Consumes: `registry.subscribe`, `events.dispatch_pending`, `OutboxEvent`, `InboxProcessed`, Task 1 models.
- Produces: `drop_draft_entries(event)` subscribed to `core.membership.removed`.

The manifest `subscribes` entry and `handlers.py` ship in this same task so startup stays valid (`import_module_code` requires a handler for every declared subscription).

- [ ] **Step 1: Write failing tests:** with timesheets enabled, create for one `user_id` a `draft`, a `submitted`, and an `approved` entry; create an `OutboxEvent(name="core.membership.removed", producer="core", payload={"user_id": <that id>})`; `events.dispatch_pending()`; assert the draft is gone and submitted/approved remain; dispatch again (force the event back to pending) and assert still exactly one deletion occurred and no error (inbox idempotency — the handler ran once; second dispatch is blocked by `(event_id, "timesheets.drop_draft_entries")`).

- [ ] **Step 2: Order the edits so startup never breaks:** add `handlers.py` (Step 3) *and* the manifest `subscribes` entry in the same change, then run the test. The test should fail on the missing-deletion assertion, not an import/startup error.

- [ ] **Step 3: Implement** `handlers.py`:

```python
from easybiz.core.kernel.registry import subscribe
from easybiz.modules.timesheets.models import Entry


@subscribe("core.membership.removed")
def drop_draft_entries(event):
    """Delete a removed member's draft time; submitted/approved/rejected is kept."""
    Entry.objects.filter(user_id=event["payload"]["user_id"], status=Entry.DRAFT).delete()
```

- [ ] **Step 4: Run — expect pass.**

- [ ] **Step 5: Gate + commit.** `git commit -m "Add Timesheets drop-draft-entries handler"`

---

### Task 7: `AttendanceProvider` capability

**Files:**
- Create: `easybiz/modules/timesheets/providers.py`
- Test: `tests/test_timesheets_capability.py`

**Interfaces:**
- Consumes: `capabilities.register`/`get`/`CapabilityUnavailable`, `AttendanceProvider` contract, Task 1 models.
- Produces: `approved_hours(user_id, start, end) -> Decimal` registered as `AttendanceProvider` for module `timesheets`.

- [ ] **Step 1: Write failing tests:** enable timesheets; create for a `user_id` two `approved` entries inside `[start,end]` and one `draft`/`submitted`/`rejected` and one `approved` outside the range; `capabilities.get(AttendanceProvider)` under `tenant_context` returns an impl whose `approved_hours` sums only the two in-range approved (e.g. `Decimal("12.50")`); after `lifecycle.disable_module(tenant, "timesheets")`, `capabilities.get(AttendanceProvider, optional=True)` returns `None` and `capabilities.get(AttendanceProvider)` raises `CapabilityUnavailable`.

- [ ] **Step 2: Run — expect fail** (no provider registered).

- [ ] **Step 3: Implement** `providers.py`: a class/impl with `approved_hours(self, user_id, start, end)` returning `Entry.objects.filter(user_id=user_id, status=Entry.APPROVED, work_date__gte=start, work_date__lte=end).aggregate(total=Sum("hours"))["total"] or Decimal("0")`; at module top call `capabilities.register(AttendanceProvider, <impl>, "timesheets")`. `import_module_code()` imports `providers.py` at startup. (The autouse `_reset_capabilities` conftest fixture restores `_providers` between tests.)

- [ ] **Step 4: Run — expect pass.**

- [ ] **Step 5: Gate + commit.** `git commit -m "Add Timesheets AttendanceProvider capability"`

---

### Task 8: Full-flow + README + milestone close

**Files:**
- Create: `tests/test_timesheets_and_events.py` (the spec's named acceptance file — full submit→approve flow + the timesheets-specific event behaviours)
- Modify: `README.md`

**Interfaces:** consumes all prior tasks.

- [ ] **Step 1: Write the end-to-end acceptance test** `tests/test_timesheets_and_events.py`: one happy path threading create→submit→approve across two users (a `timesheet_user` author and a `timesheet_approver` reviewer via `_add_user`), asserting the status transitions, the audit rows, and the published `timesheets.entry.approved` event; plus a menu-follows-permissions assertion (a `timesheet_user` token's `GET /api/auth/me` menu includes "Timesheets" but not "Projects"; an approver sees both). Reference the generic engine properties (undeclared-publish, parked/replay, retry/dead) as covered by `test_events_*.py` in a module docstring-free comment at the import site per the scope ruling.

- [ ] **Step 2: Run — expect pass** (all behaviours already implemented; this is the integration proof). If any assertion fails, fix via systematic-debugging, not by weakening the test.

- [ ] **Step 3: Update README** — Status: **M6 complete** (Timesheets reference module: models + migration, `/api/timesheets` projects & entries & review, approved/rejected events, `core.membership.removed` → drop-drafts handler, `AttendanceProvider` capability, default roles + menu; module API routers now auto-mounted). Add `provision_tenant ... --modules timesheets` to examples. Next: **M7** (platform API).

- [ ] **Step 4: Full gate.** `uv run pytest && uv run ruff check . && uv run ruff format --check . && uv run mypy easybiz config && uv run manage.py makemigrations --check --dry-run`

- [ ] **Step 5: Commit.** `git add tests/test_timesheets_and_events.py README.md && git commit -m "Add Timesheets end-to-end acceptance test and document M6"`

---

## M6 Definition of Done

- [ ] `timesheets` enables into a tenant: `timesheets_project`/`timesheets_entry` tables created only then; `makemigrations --check` clean.
- [ ] `/api/timesheets/projects` (read/manage, code uppercased, dup→409) and `/api/timesheets/entries` (create with hours bounds + active-project check, own-vs-all visibility, submit rules) enforce their permission codes.
- [ ] Approve/reject require `entry.approve`, reject self-review with 403, require `submitted` (409), and publish `timesheets.entry.approved`/`.rejected` with the §8.4 payload (hours as string) in the same transaction as the status change + audit.
- [ ] `core.membership.removed` deletes only the removed user's `draft` entries (submitted/approved/rejected kept) and is idempotent on redelivery.
- [ ] `AttendanceProvider.approved_hours` sums only in-range `approved` hours and is available only while timesheets is enabled (`None`/`CapabilityUnavailable` otherwise).
- [ ] Module API routers auto-mount at `/api/<id>`; a non-enabling tenant gets 404 on `/api/timesheets/...` (ModuleGate).
- [ ] `test_timesheets_and_events.py` and `test_module_lifecycle.py` pass; full suite green on real Postgres; ruff/format/mypy clean; commits short, no attribution.
