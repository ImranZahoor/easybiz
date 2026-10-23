# Easybiz M3a (Module System Core) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the per-tenant module system: catalog + iam/audit/events models, the module-aware migration mechanism (module tables exist only where enabled), `state.py`, `lifecycle.py` (enable/disable/remove/upgrade), `capabilities.py`, a minimal `demo` module to enable, the `sync_modules`/`tenant_module` commands, and `init_platform` catalog sync.

**Architecture:** Catalog models live in `public` (shared); `iam`/`audit`/`events` models live in each tenant schema. A DB router + a per-schema migrate command cooperate so a module's tables are created in a tenant schema only when a `catalog_tenantmodule` row exists for it (invariant I4). `lifecycle.enable_module` creates that row, migrates the module into the one schema, seeds the module's default roles, and writes an audit row + outbox event. M3a is the first milestone that creates tenant schemas and module tables, so it exercises the real django-tenants migration path.

**Tech Stack:** Django 6.1 + django-tenants (TenantSyncRouter, `migrate_schemas`, `schema_context`/`tenant_context`), PostgreSQL 16, psycopg 3, pytest; `uv`.

**Spec:** `ERP-CORE-SPEC.md` — data model (§4.1 catalog, §4.2 iam/audit/events), migration mechanism (§5.5), state (§5.4), lifecycle (§5.6), capabilities (§5.8), `requeue_parked` (§5.9), commands (§3.5), M3 (§11), invariants I2/I3/I4/I12/I13/I15.

## Scope decision (rulings, user-approved)

- **M3a is the first half of M3** (the split you approved). **M3b** adds `provisioning.py`, tenant ops (suspend/resume/domains/delete), and the `provision_tenant`/`upgrade_modules` CLI. M3a creates tenants directly via `Tenant.objects.create` in tests (provisioning is M3b).
- **Forward-dependency handling:** `iam`/`audit`/`events` ship as **models only** (per §11 M3). `lifecycle.py` writes directly to those models (seed `iam_*` rows, create an `audit_auditlog` row, create an `events_outboxevent` row). The polished `iam/service.py`, `audit/service.py`, `events/service.py` arrive in M4/M5 and lifecycle is refactored onto them then.
- **`requeue_parked`** is implemented against `OutboxEvent` but is effectively a no-op in M3a (no dispatcher until M5; `parked` is always empty). Included so enable's contract is complete.
- **`ModuleGateMiddleware`/`TenantStatusMiddleware` stay pass-through stubs** (M0); their activation is M4 per §11. M3a does not touch middleware.
- A minimal **`demo` module** (`easybiz.modules.demo`: one table, one permission, one default role) is the "something to enable." It ships in `EASYBIZ_MODULES`; timesheets gets real content in M6.

## Global Constraints

- Python 3.13; Django ≥5.2 (6.1); django-tenants ≥3.8; PostgreSQL 16 via psycopg 3; `uv`; pytest (DB required: `docker compose up -d db`).
- **I2:** no cross-schema FKs; tenant→user references are UUID values. **I3:** catalog in `public`, tenant data in tenant schema. **I4:** a module's tables exist only in schemas with a `catalog_tenantmodule` row. **I12:** `migrate_schemas` resets the connection to `public`; restore after. **I13:** inside `schema_context` the tenant is a pk-less stub; resolve by `schema_name`. **I15:** real PostgreSQL only.
- IDs: business entities UUID pk; infra join tables `BigAutoField`. Migrations generated with `makemigrations`, committed.
- `LifecycleError` for all lifecycle failures (APIs map to 409 in M4). Management command names unique.
- §0.5: short commits, no attribution; docstrings on public functions; types in `types.py` where schema types arise; `ruff` + `mypy easybiz config` clean.

## Review Focus

Each pinned to the task that owns it.

- **Module tables land only where enabled (I4):** after enabling `demo` for tenant A but not B, `demo_*` exists in A's schema, not in B's, not in `public`; and B's `django_migrations` has no `demo` row. → Task 6.
- **`migrate_schemas` connection reset (I12):** enabling a module must leave `connection` back on the caller's tenant/public afterward. → Task 6.
- **Stub-tenant resolution (I13):** `state.is_enabled` must work when called inside `schema_context`/`tenant_context` (pk-less tenant) by resolving on `schema_name`; `public` resolves to nothing enabled. → Task 3.
- **Enable idempotency / guards:** enabling an already-enabled module, an unknown module, or one whose `requires` aren't enabled must raise `LifecycleError`; disable refused while an enabled module requires it; remove refused unless disabled. → Task 6.
- **Capability gating:** `capabilities.get` returns the impl only while the provider's module is enabled for `connection.tenant`; else `None` (optional) or `CapabilityUnavailable`. → Task 7.

---

### Task 1: Catalog models (public)

**Files:**
- Modify: `easybiz/core/catalog/models.py`
- Create (generated): `easybiz/core/catalog/migrations/0001_initial.py`
- Test: `tests/test_catalog_models.py`

**Interfaces:**
- Consumes: `tenancy.Tenant`.
- Produces: `catalog.Module` (char(32) pk `id`), `catalog.TenantModule` (FK tenant cascade `related_name="modules"`, FK module PROTECT, `status`, `installed_version`, `enabled_at`, unique `(tenant, module)`), `catalog.Permission` (char(100) pk `code`, FK module null).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_catalog_models.py
def test_catalog_tables_exist_in_public(tables_in):
    assert {"catalog_module", "catalog_tenantmodule", "catalog_permission"} <= tables_in("public")
```

- [ ] **Step 2: Run — expect fail** (`uv run pytest tests/test_catalog_models.py -v` → tables missing).

- [ ] **Step 3: Write `easybiz/core/catalog/models.py`**

```python
from django.db import models


class Module(models.Model):
    """System-wide record of an installed module (its parsed manifest)."""

    id = models.CharField(max_length=32, primary_key=True)
    name = models.CharField(max_length=200)
    version = models.CharField(max_length=20)
    manifest = models.JSONField()
    installed_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class TenantModule(models.Model):
    """Per-tenant enablement state for a module."""

    ENABLING, ENABLED, DISABLED = "enabling", "enabled", "disabled"
    STATUS = [(ENABLING, ENABLING), (ENABLED, ENABLED), (DISABLED, DISABLED)]

    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="modules")
    module = models.ForeignKey(Module, on_delete=models.PROTECT)
    status = models.CharField(max_length=10, choices=STATUS)
    installed_version = models.CharField(max_length=20)
    enabled_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "module"], name="uniq_tenant_module")
        ]


class Permission(models.Model):
    """Assignable permission code; null module = core permission."""

    code = models.CharField(max_length=100, primary_key=True)
    module = models.ForeignKey(Module, on_delete=models.CASCADE, null=True, blank=True)
    description = models.CharField(max_length=300, blank=True)
```

- [ ] **Step 4: Generate + apply migration, run test**

Run: `uv run manage.py makemigrations catalog && uv run pytest tests/test_catalog_models.py -v`
Expected: migration created; test PASS (the session fixture runs `migrate_schemas --shared`).

- [ ] **Step 5: Commit**

```bash
git add easybiz/core/catalog tests/test_catalog_models.py
git commit -m "Add catalog models (module, tenant-module, permission)"
```

---

### Task 2: iam / audit / events models (tenant schema)

**Files:**
- Modify: `easybiz/core/iam/models.py`, `easybiz/core/audit/models.py`, `easybiz/core/events/models.py`
- Create (generated): `0001_initial.py` under each app's `migrations/`

**Interfaces:**
- Produces (tenant-schema tables): `iam.Role/RolePermission/UserRole`, `audit.AuditLog`, `events.OutboxEvent/InboxProcessed`, per §4.2. No cross-schema FKs (user referenced by UUID value).

- [ ] **Step 1: Write `iam/models.py`**

```python
import uuid

from django.db import models


class Role(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100, unique=True)
    description = models.CharField(max_length=300, blank=True)
    is_system = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)


class RolePermission(models.Model):
    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name="permissions")
    permission = models.CharField(max_length=100)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["role", "permission"], name="uniq_role_permission")
        ]


class UserRole(models.Model):
    user_id = models.UUIDField(db_index=True)  # references users_user by value (I2)
    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name="assignments")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user_id", "role"], name="uniq_user_role")
        ]
```

- [ ] **Step 2: Write `audit/models.py`**

```python
import uuid

from django.db import models


class AuditLog(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    at = models.DateTimeField(auto_now_add=True, db_index=True)
    actor_id = models.UUIDField(null=True, blank=True)
    action = models.CharField(max_length=100, db_index=True)
    entity = models.CharField(max_length=100, blank=True)
    entity_id = models.CharField(max_length=100, blank=True)
    before = models.JSONField(null=True, blank=True)
    after = models.JSONField(null=True, blank=True)
```

- [ ] **Step 3: Write `events/models.py`**

```python
import uuid

from django.db import models
from django.utils import timezone


class OutboxEvent(models.Model):
    PENDING, DONE, DEAD = "pending", "done", "dead"
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=120, db_index=True)
    producer = models.CharField(max_length=32)
    payload = models.JSONField(default=dict)
    version = models.SmallIntegerField(default=1)
    status = models.CharField(max_length=10, default=PENDING, db_index=True)
    attempts = models.SmallIntegerField(default=0)
    next_attempt_at = models.DateTimeField(default=timezone.now)
    last_error = models.TextField(blank=True)
    parked = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)


class InboxProcessed(models.Model):
    event_id = models.UUIDField(db_index=True)
    handler = models.CharField(max_length=160)
    processed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["event_id", "handler"], name="uniq_event_handler")
        ]
```

- [ ] **Step 4: Generate migrations**

Run: `uv run manage.py makemigrations iam audit events`
Expected: `0001_initial` under each.

- [ ] **Step 5: Verify shared migrate unaffected + suite green**

Run: `uv run pytest`
Expected: green (these are TENANT_APPS; `migrate_schemas --shared` does not create them in `public`, and no tenant exists yet).

- [ ] **Step 6: Commit**

```bash
git add easybiz/core/iam easybiz/core/audit easybiz/core/events
git commit -m "Add iam, audit, and events models"
```

---

### Task 3: `state.py` — enabled-module lookups

**Files:**
- Create: `easybiz/core/kernel/state.py`
- Test: `tests/test_state.py`

**Interfaces:**
- Consumes: `catalog.TenantModule`, `tenancy.Tenant`, django-tenants public schema name.
- Produces: `enabled_module_ids(tenant) -> set[str]`, `is_enabled(tenant, module_id) -> bool`. Accepts a real `Tenant` or a pk-less stub (resolves by `schema_name`, I13). `public` → empty.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_state.py
import pytest

from easybiz.core.catalog.models import Module, TenantModule
from easybiz.core.kernel import state
from easybiz.core.tenancy.models import Tenant


@pytest.fixture
def tenant_with_module(db_tenant):
    mod = Module.objects.create(id="demo", name="Demo", version="0.1.0", manifest={})
    TenantModule.objects.create(
        tenant=db_tenant, module=mod, status=TenantModule.ENABLED, installed_version="0.1.0"
    )
    return db_tenant


def test_is_enabled_true_for_enabled_module(tenant_with_module):
    assert state.is_enabled(tenant_with_module, "demo") is True


def test_is_enabled_false_for_disabled(db_tenant):
    mod = Module.objects.create(id="demo", name="Demo", version="0.1.0", manifest={})
    TenantModule.objects.create(
        tenant=db_tenant, module=mod, status=TenantModule.DISABLED, installed_version="0.1.0"
    )
    assert state.is_enabled(db_tenant, "demo") is False


def test_public_tenant_has_nothing_enabled():
    public = Tenant.objects.get(schema_name="public")
    assert state.enabled_module_ids(public) == set()
```

Add a `db_tenant` fixture to `tests/conftest.py` that creates a throwaway tenant schema and cleans it up:

```python
@pytest.fixture
def db_tenant():
    from easybiz.core.tenancy.models import Domain, Tenant

    tenant = Tenant(schema_name="t_state", slug="state", name="State")
    tenant.save()  # auto_create_schema migrates core tenant apps into t_state
    Domain.objects.create(domain="state.localhost", tenant=tenant, is_primary=True)
    connection.set_schema_to_public()
    yield tenant
    from django.db import connection as conn

    with conn.cursor() as cur:
        cur.execute('DROP SCHEMA IF EXISTS "t_state" CASCADE')
    Tenant.objects.filter(schema_name="t_state").delete()
```

- [ ] **Step 2: Run — expect fail** (`state` module missing; and note: creating the tenant also proves the migrate command works once Task 5 lands — until then `t_state` may include `demo` tables, which is fine for this test).

- [ ] **Step 3: Write `state.py`**

```python
"""Enabled-module lookups that tolerate the pk-less stub tenant (I13)."""
from __future__ import annotations

from django_tenants.utils import get_public_schema_name

from easybiz.core.catalog.models import TenantModule


def _schema_name(tenant) -> str | None:
    return getattr(tenant, "schema_name", None)


def enabled_module_ids(tenant) -> set[str]:
    schema = _schema_name(tenant)
    if schema is None or schema == get_public_schema_name():
        return set()
    return set(
        TenantModule.objects.filter(
            tenant__schema_name=schema, status=TenantModule.ENABLED
        ).values_list("module_id", flat=True)
    )


def is_enabled(tenant, module_id: str) -> bool:
    return module_id in enabled_module_ids(tenant)
```

- [ ] **Step 4: Run — expect pass** (`uv run pytest tests/test_state.py -v`).

- [ ] **Step 5: Commit**

```bash
git add easybiz/core/kernel/state.py tests/test_state.py tests/conftest.py
git commit -m "Add state helpers for enabled-module lookups"
```

---

### Task 4: Minimal `demo` module

**Files:**
- Create: `easybiz/modules/demo/{__init__.py, apps.py, models.py, manifest.json}` and `migrations/__init__.py`
- Modify: `.env.example`, and the default in `config/settings.py` (`EASYBIZ_MODULES` default) to include demo

**Interfaces:**
- Produces: Django app `demo` (label `demo`, name `easybiz.modules.demo`) with one tenant-schema table `demo_widget`, permission `demo.widget.read`, default role `demo_viewer`.

- [ ] **Step 1: Create the package**

`easybiz/modules/demo/__init__.py` empty. `apps.py`:

```python
from django.apps import AppConfig


class DemoConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "easybiz.modules.demo"
    label = "demo"
```

`models.py`:

```python
import uuid

from django.db import models


class Widget(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)
```

`manifest.json`:

```json
{
  "id": "demo",
  "name": "Demo",
  "version": "0.1.0",
  "permissions": [{"code": "demo.widget.read", "description": "See demo widgets"}],
  "roles": [{"name": "demo_viewer", "description": "Views widgets", "permissions": ["demo.widget.read"]}],
  "events": {"publishes": [], "subscribes": []},
  "menu": []
}
```

- [ ] **Step 2: Register demo in settings default + env**

In `config/settings.py` change the `EASYBIZ_MODULES` default to `"easybiz.modules.timesheets,easybiz.modules.demo"`; mirror in `.env.example`.

- [ ] **Step 3: Generate the migration**

Run: `uv run manage.py makemigrations demo`
Expected: `0001_initial` creating `Widget`.

- [ ] **Step 4: Verify startup still green**

Run: `uv run manage.py check && uv run pytest`
Expected: registry loads demo's manifest at startup; suite green (demo is a TENANT_APP, not migrated into `public`; `t_state` from the Task 3 fixture may get a `demo_widget` table until Task 5 — acceptable).

- [ ] **Step 5: Commit**

```bash
git add easybiz/modules/demo config/settings.py .env.example
git commit -m "Add minimal demo module"
```

---

### Task 5: Module-aware migration mechanism

**Files:**
- Modify: `easybiz/core/kernel/routers.py`, `easybiz/core/kernel/migrate.py`
- Test: `tests/test_module_migrations.py`

**Interfaces:**
- Consumes: `registry` (module ids), `catalog_tenantmodule` (raw SQL), django-tenants schema context.
- Produces: `ModuleAwareTenantSyncRouter.allow_migrate` gating module apps by catalog row; `migrate.Command` hiding absent modules per schema. `module_has_tables(schema, app_label) -> bool`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_module_migrations.py
def test_fresh_tenant_has_core_tables_but_no_module_tables(db_tenant, tables_in):
    schema = db_tenant.schema_name
    tables = tables_in(schema)
    assert {"iam_role", "audit_auditlog", "events_outboxevent"} <= tables
    assert "demo_widget" not in tables  # no TenantModule row => router hides it


def test_module_tables_never_in_public(tables_in):
    assert "demo_widget" not in tables_in("public")
```

- [ ] **Step 2: Run — expect fail** (with the M0 stub router, `db_tenant` creation migrates `demo_widget` into `t_state`).

- [ ] **Step 3: Implement `routers.py`**

```python
"""DB router: a module's tables migrate into a tenant schema only when enabled."""
from __future__ import annotations

from django.db import connection
from django_tenants.routers import TenantSyncRouter
from django_tenants.utils import get_public_schema_name


def module_has_tables(schema_name: str, app_label: str) -> bool:
    """True if the tenant has any catalog_tenantmodule row for the module (any status)."""
    with connection.cursor() as cur:
        cur.execute(
            'SELECT 1 FROM "public".catalog_tenantmodule tm '
            'JOIN "public".tenancy_tenant t ON t.id = tm.tenant_id '
            "WHERE t.schema_name = %s AND tm.module_id = %s LIMIT 1",
            [schema_name, app_label],
        )
        return cur.fetchone() is not None


class ModuleAwareTenantSyncRouter(TenantSyncRouter):
    def _is_module_app(self, app_label: str) -> bool:
        from easybiz.core.kernel.registry import registry

        return registry.manifest(app_label) is not None

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        decision = super().allow_migrate(db, app_label, model_name, **hints)
        if not self._is_module_app(app_label):
            return decision
        schema = getattr(connection, "schema_name", None)
        if schema is None or schema == get_public_schema_name():
            return False
        return module_has_tables(schema, app_label)
```

- [ ] **Step 4: Implement `migrate.py`**

```python
"""Per-schema migrate that hides module apps the current schema does not have,
so Django records no migration state for them (closes pitfall P2)."""
from __future__ import annotations

from django.conf import settings
from django.core.management.commands.migrate import Command as MigrateCommand
from django.db import connection
from django.test.utils import override_settings
from django_tenants.utils import get_public_schema_name

from easybiz.core.kernel.routers import module_has_tables


class Command(MigrateCommand):
    def handle(self, *args, **options):
        from easybiz.core.kernel.registry import registry

        schema = getattr(connection, "schema_name", None) or get_public_schema_name()
        public = schema == get_public_schema_name()
        hidden = {}
        for module_id in registry.module_ids():
            if public or not module_has_tables(schema, module_id):
                hidden[module_id] = None
        existing = getattr(settings, "MIGRATION_MODULES", {})
        with override_settings(MIGRATION_MODULES={**existing, **hidden}):
            super().handle(*args, **options)
```

Add `Registry.module_ids()` to `registry.py`:

```python
    def module_ids(self) -> list[str]:
        return list(self._manifests)
```

- [ ] **Step 5: Run — expect pass**

Run: `uv run pytest tests/test_module_migrations.py tests/test_state.py -v`
Expected: PASS — a fresh tenant gets core tenant tables but not `demo_widget`; `public` never has `demo_widget`.
Note (library check): `module_has_tables` runs raw SQL on the current connection; it reads `public.*` tables, reachable from any schema's `search_path`. If `connection.schema_name` is unavailable in the router during `makemigrations` (no schema set), the `None` guard returns the parent decision / False safely.

- [ ] **Step 6: Commit**

```bash
git add easybiz/core/kernel/routers.py easybiz/core/kernel/migrate.py easybiz/core/kernel/registry.py tests/test_module_migrations.py
git commit -m "Add module-aware migration router and per-schema migrate"
```

---

### Task 6: `lifecycle.py` — enable / disable / remove / upgrade

**Files:**
- Create: `easybiz/core/kernel/lifecycle.py`
- Test: `tests/test_lifecycle.py`

**Interfaces:**
- Consumes: `registry`, `catalog.Module/TenantModule/Permission`, `iam.Role/RolePermission`, `audit.AuditLog`, `events.OutboxEvent`, `state`, django-tenants `schema_context`/`tenant_context`, `call_command("migrate_schemas", ...)`.
- Produces: `LifecycleError`; `install_module(id)`, `sync_catalog() -> list[str]`, `enable_module(tenant, id, actor_id=None)`, `disable_module(tenant, id, actor_id=None)`, `remove_module_data(tenant, id, actor_id=None, policy="drop")`, `upgrade_modules()`, `requeue_parked(module_id) -> int`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_lifecycle.py
import pytest
from django_tenants.utils import tenant_context

from easybiz.core.catalog.models import Permission, TenantModule
from easybiz.core.iam.models import Role
from easybiz.core.kernel import lifecycle, state


@pytest.fixture
def synced():
    lifecycle.sync_catalog()


def test_sync_catalog_installs_demo_permission(synced):
    assert Permission.objects.filter(code="demo.widget.read").exists()


def test_enable_creates_tables_and_roles_in_that_tenant_only(synced, db_tenant, tables_in):
    lifecycle.enable_module(db_tenant, "demo")
    assert "demo_widget" in tables_in(db_tenant.schema_name)
    assert state.is_enabled(db_tenant, "demo") is True
    with tenant_context(db_tenant):
        assert Role.objects.filter(name="demo_viewer").exists()
    # connection restored to public after migrate (I12)
    from django.db import connection
    from django_tenants.utils import get_public_schema_name
    assert connection.schema_name == get_public_schema_name()


def test_enable_twice_raises(synced, db_tenant):
    lifecycle.enable_module(db_tenant, "demo")
    with pytest.raises(lifecycle.LifecycleError):
        lifecycle.enable_module(db_tenant, "demo")


def test_enable_unknown_module_raises(synced, db_tenant):
    with pytest.raises(lifecycle.LifecycleError):
        lifecycle.enable_module(db_tenant, "nope")


def test_disable_keeps_tables_then_reenable(synced, db_tenant, tables_in):
    lifecycle.enable_module(db_tenant, "demo")
    lifecycle.disable_module(db_tenant, "demo")
    assert state.is_enabled(db_tenant, "demo") is False
    assert "demo_widget" in tables_in(db_tenant.schema_name)  # data kept
    lifecycle.enable_module(db_tenant, "demo")
    assert state.is_enabled(db_tenant, "demo") is True


def test_remove_requires_disable_then_drops_tables(synced, db_tenant, tables_in):
    lifecycle.enable_module(db_tenant, "demo")
    with pytest.raises(lifecycle.LifecycleError):
        lifecycle.remove_module_data(db_tenant, "demo")  # still enabled
    lifecycle.disable_module(db_tenant, "demo")
    lifecycle.remove_module_data(db_tenant, "demo")
    assert "demo_widget" not in tables_in(db_tenant.schema_name)
    assert not TenantModule.objects.filter(tenant=db_tenant, module_id="demo").exists()
```

- [ ] **Step 2: Run — expect fail** (`lifecycle` missing).

- [ ] **Step 3: Implement `lifecycle.py`**

```python
"""Per-tenant module lifecycle: install, enable, disable, remove, upgrade."""
from __future__ import annotations

from contextlib import contextmanager

from django.core.management import call_command
from django.db import connection, transaction
from django.utils import timezone
from django_tenants.utils import get_public_schema_name, schema_context, tenant_context

from easybiz.core.audit.models import AuditLog
from easybiz.core.catalog.models import Module, Permission, TenantModule
from easybiz.core.events.models import OutboxEvent
from easybiz.core.iam.models import Role, RolePermission
from easybiz.core.kernel.manifest import Version, VersionRange
from easybiz.core.kernel.registry import registry


class LifecycleError(Exception):
    """Raised for any invalid module lifecycle transition (maps to HTTP 409)."""


@contextmanager
def _keep_connection_tenant():
    """Restore the connection's schema after a call that resets it (I12)."""
    schema = connection.schema_name
    try:
        yield
    finally:
        connection.set_schema_to_public() if schema == get_public_schema_name() else None
        if schema != get_public_schema_name():
            from easybiz.core.tenancy.models import Tenant

            connection.set_tenant(Tenant.objects.get(schema_name=schema))


def install_module(module_id: str) -> None:
    manifest = registry.manifest(module_id)
    if manifest is None:
        raise LifecycleError(f"module {module_id!r} is not installed on disk")
    with transaction.atomic():
        Module.objects.update_or_create(
            id=manifest.id,
            defaults={"name": manifest.name, "version": manifest.version, "manifest": _as_dict(manifest)},
        )
        declared = {code for code, _ in manifest.permissions}
        for code, desc in manifest.permissions:
            Permission.objects.update_or_create(
                code=code, defaults={"module_id": manifest.id, "description": desc}
            )
        Permission.objects.filter(module_id=manifest.id).exclude(code__in=declared).delete()


def sync_catalog() -> list[str]:
    order = registry.load_order()
    for module_id in order:
        install_module(module_id)
    return order


def enable_module(tenant, module_id: str, actor_id=None) -> None:
    manifest = registry.manifest(module_id)
    if manifest is None or not Module.objects.filter(id=module_id).exists():
        raise LifecycleError(f"module {module_id!r} is not in the catalog")
    if state.is_enabled(tenant, module_id):
        raise LifecycleError(f"module {module_id!r} is already enabled")
    _assert_requirements_enabled(tenant, manifest)

    with _keep_connection_tenant():
        row, created = TenantModule.objects.get_or_create(
            tenant=tenant,
            module_id=module_id,
            defaults={"status": TenantModule.ENABLING, "installed_version": manifest.version},
        )
        try:
            call_command("migrate_schemas", module_id, schema_name=tenant.schema_name, verbosity=0)
        except Exception as exc:  # noqa: BLE001 - re-raised as LifecycleError
            if created:
                row.delete()
            else:
                row.status = TenantModule.DISABLED
                row.save(update_fields=["status"])
            raise LifecycleError(f"migrations for {module_id!r} failed: {exc}") from exc

    with tenant_context(tenant):
        with transaction.atomic():
            _seed_roles(manifest)
            requeue_parked(module_id)
            AuditLog.objects.create(
                actor_id=actor_id, action="module.enabled", entity="module", entity_id=module_id,
                after={"version": manifest.version},
            )
            OutboxEvent.objects.create(
                name="core.module.enabled", producer="core",
                payload={"module": module_id, "version": manifest.version},
            )
    TenantModule.objects.filter(tenant=tenant, module_id=module_id).update(
        status=TenantModule.ENABLED, installed_version=manifest.version, enabled_at=timezone.now()
    )


def disable_module(tenant, module_id: str, actor_id=None) -> None:
    if not state.is_enabled(tenant, module_id):
        raise LifecycleError(f"module {module_id!r} is not enabled")
    blockers = _enabled_dependents(tenant, module_id)
    if blockers:
        raise LifecycleError(f"cannot disable {module_id!r}; required by {sorted(blockers)}")
    TenantModule.objects.filter(tenant=tenant, module_id=module_id).update(status=TenantModule.DISABLED)
    with tenant_context(tenant):
        with transaction.atomic():
            AuditLog.objects.create(actor_id=actor_id, action="module.disabled", entity="module", entity_id=module_id)
            OutboxEvent.objects.create(name="core.module.disabled", producer="core", payload={"module": module_id})


def remove_module_data(tenant, module_id: str, actor_id=None, policy: str = "drop") -> None:
    if policy != "drop":
        raise LifecycleError("only policy='drop' is supported")
    row = TenantModule.objects.filter(tenant=tenant, module_id=module_id).first()
    if row is None or row.status != TenantModule.DISABLED:
        raise LifecycleError(f"module {module_id!r} must be disabled before data removal")
    if _dependents_with_row(tenant, module_id):
        raise LifecycleError(f"cannot remove {module_id!r}; dependents still hold data")
    with _keep_connection_tenant():
        call_command("migrate_schemas", module_id, "zero", schema_name=tenant.schema_name, verbosity=0)
    manifest = registry.manifest(module_id)
    codes = {code for code, _ in manifest.permissions} if manifest else set()
    with tenant_context(tenant):
        with transaction.atomic():
            RolePermission.objects.filter(permission__in=codes).delete()
            AuditLog.objects.create(actor_id=actor_id, action="module.data_removed", entity="module", entity_id=module_id)
    row.delete()


def upgrade_modules() -> list[str]:
    order = sync_catalog()
    call_command("migrate_schemas", verbosity=0)
    for row in TenantModule.objects.select_related("module"):
        manifest = registry.manifest(row.module_id)
        if manifest:
            TenantModule.objects.filter(pk=row.pk).update(installed_version=manifest.version)
    return order


def requeue_parked(module_id: str) -> int:
    count = 0
    for event in OutboxEvent.objects.filter(parked__contains=module_id):
        event.parked = [m for m in event.parked if m != module_id]
        event.status = OutboxEvent.PENDING
        event.next_attempt_at = timezone.now()
        event.save(update_fields=["parked", "status", "next_attempt_at"])
        count += 1
    return count


# --- helpers -----------------------------------------------------------------

def _as_dict(manifest) -> dict:
    return {
        "id": manifest.id, "name": manifest.name, "version": manifest.version,
        "requires": [list(d) for d in manifest.requires], "optional": [list(d) for d in manifest.optional],
        "provides": manifest.provides, "consumes": manifest.consumes,
        "permissions": [list(p) for p in manifest.permissions], "roles": manifest.roles,
        "publishes": manifest.publishes, "subscribes": manifest.subscribes, "menu": manifest.menu,
    }


def _assert_requirements_enabled(tenant, manifest) -> None:
    for dep, rng in manifest.requires:
        if not state.is_enabled(tenant, dep):
            raise LifecycleError(f"module {manifest.id!r} requires {dep!r} to be enabled first")
        dep_manifest = registry.manifest(dep)
        if dep_manifest and not VersionRange.parse(rng).contains(Version.parse(dep_manifest.version)):
            raise LifecycleError(f"module {manifest.id!r} requires {dep!r} {rng}")


def _enabled_dependents(tenant, module_id: str) -> set[str]:
    enabled = state.enabled_module_ids(tenant)
    return {d for d in registry.dependents_of(module_id) if d in enabled}


def _dependents_with_row(tenant, module_id: str) -> set[str]:
    have_rows = set(
        TenantModule.objects.filter(tenant=tenant).values_list("module_id", flat=True)
    )
    return {d for d in registry.dependents_of(module_id) if d in have_rows}


def _seed_roles(manifest) -> None:
    for role in manifest.roles:
        obj, created = Role.objects.get_or_create(
            name=role["name"], defaults={"description": role.get("description", ""), "is_system": False}
        )
        if created:
            for perm in role.get("permissions", []):
                RolePermission.objects.create(role=obj, permission=perm)
```

`import ... state` is used; add `from easybiz.core.kernel import state` to the imports.

- [ ] **Step 4: Run the lifecycle tests, fixing `migrate_schemas` invocation against the real library**

Run: `uv run pytest tests/test_lifecycle.py -v`
Expected: PASS. **Library check:** the exact kwarg for a single schema in `migrate_schemas` (`schema_name=` vs `schema=`) must match this django-tenants version — if it errors on an unknown option, inspect `migrate_schemas --help`, use the right one, and record it in spec §12. Likewise confirm `connection.set_tenant`/`set_schema_to_public` are the right restore calls for I12.

- [ ] **Step 5: Full suite + gate**

Run: `uv run pytest && uv run ruff check . && uv run mypy easybiz config`
Expected: green.

- [ ] **Step 6: Commit**

```bash
git add easybiz/core/kernel/lifecycle.py tests/test_lifecycle.py
git commit -m "Add module lifecycle (enable, disable, remove, upgrade)"
```

---

### Task 7: `capabilities.py`

**Files:**
- Create: `easybiz/core/kernel/capabilities.py`
- Test: `tests/test_capabilities.py`

**Interfaces:**
- Consumes: `state.is_enabled`, `connection.tenant`.
- Produces: `CapabilityUnavailable`; `register(contract, impl, module_id)`; `get(contract, optional=False)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_capabilities.py
import pytest
from django_tenants.utils import tenant_context

from easybiz.core.kernel import capabilities, lifecycle


class _Contract:  # stand-in contract type
    pass


class _Impl:
    pass


def test_capability_only_while_enabled(synced, db_tenant):
    impl = _Impl()
    capabilities.register(_Contract, impl, "demo")
    with tenant_context(db_tenant):
        assert capabilities.get(_Contract, optional=True) is None  # demo not enabled
    lifecycle.enable_module(db_tenant, "demo")
    with tenant_context(db_tenant):
        assert capabilities.get(_Contract) is impl


def test_missing_capability_raises(db_tenant):
    with pytest.raises(capabilities.CapabilityUnavailable):
        with tenant_context(db_tenant):
            capabilities.get(_Contract)
```

(Reuse the `synced` fixture — move it to `conftest.py` so both lifecycle and capability tests share it.)

- [ ] **Step 2: Run — expect fail.**

- [ ] **Step 3: Implement `capabilities.py`**

```python
"""Capability registry: resolve a contract only while its provider is enabled."""
from __future__ import annotations

from django.db import connection

from easybiz.core.kernel import state


class CapabilityUnavailable(Exception):
    """Raised when a requested capability's provider module is not enabled."""


_providers: dict[type, tuple[object, str]] = {}


def register(contract: type, impl: object, module_id: str) -> None:
    _providers[contract] = (impl, module_id)


def get(contract: type, optional: bool = False):
    entry = _providers.get(contract)
    if entry is not None:
        impl, module_id = entry
        tenant = getattr(connection, "tenant", None)
        if tenant is not None and state.is_enabled(tenant, module_id):
            return impl
    if optional:
        return None
    raise CapabilityUnavailable(f"no enabled provider for {getattr(contract, '__name__', contract)!r}")
```

- [ ] **Step 4: Run — expect pass; then gate.**

- [ ] **Step 5: Commit**

```bash
git add easybiz/core/kernel/capabilities.py tests/test_capabilities.py tests/conftest.py
git commit -m "Add capability registry gated by module enablement"
```

---

### Task 8: Commands + `init_platform` catalog sync

**Files:**
- Create: `easybiz/core/kernel/management/commands/sync_modules.py`, `easybiz/core/kernel/management/commands/tenant_module.py`
- Modify: `easybiz/core/kernel/management/commands/init_platform.py`
- Test: `tests/test_module_commands.py`

**Interfaces:**
- Produces: `sync_modules` (calls `sync_catalog`), `tenant_module <slug> enable|disable|remove <module>`; `init_platform` now also runs `sync_catalog`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_module_commands.py
from django.core.management import call_command

from easybiz.core.catalog.models import Module, TenantModule
from easybiz.core.kernel import state


def test_sync_modules_populates_catalog():
    call_command("sync_modules", verbosity=0)
    assert Module.objects.filter(id="demo").exists()


def test_tenant_module_enable_disable(db_tenant):
    call_command("sync_modules", verbosity=0)
    call_command("tenant_module", db_tenant.slug, "enable", "demo", verbosity=0)
    assert state.is_enabled(db_tenant, "demo") is True
    call_command("tenant_module", db_tenant.slug, "disable", "demo", verbosity=0)
    assert state.is_enabled(db_tenant, "demo") is False
```

- [ ] **Step 2: Run — expect fail.**

- [ ] **Step 3: Implement `sync_modules.py`**

```python
from django.core.management.base import BaseCommand

from easybiz.core.kernel import lifecycle


class Command(BaseCommand):
    """Record every module found on disk, and core permissions, in the catalog."""

    def handle(self, *args, **options):
        order = lifecycle.sync_catalog()
        self.stdout.write(f"synced: {', '.join(order)}")
```

- [ ] **Step 4: Implement `tenant_module.py`**

```python
from django.core.management.base import BaseCommand, CommandError

from easybiz.core.kernel import lifecycle
from easybiz.core.tenancy.models import Tenant

_ACTIONS = {"enable": lifecycle.enable_module, "disable": lifecycle.disable_module, "remove": lifecycle.remove_module_data}


class Command(BaseCommand):
    """Per-tenant module lifecycle from the CLI."""

    def add_arguments(self, parser):
        parser.add_argument("slug")
        parser.add_argument("action", choices=sorted(_ACTIONS))
        parser.add_argument("module")

    def handle(self, *args, **options):
        tenant = Tenant.objects.filter(slug=options["slug"]).first()
        if tenant is None:
            raise CommandError(f"no tenant with slug {options['slug']!r}")
        try:
            _ACTIONS[options["action"]](tenant, options["module"])
        except lifecycle.LifecycleError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(f"{options['action']} {options['module']} for {options['slug']}: ok")
```

- [ ] **Step 5: Extend `init_platform` to sync the catalog**

Add, after seeding the public tenant + domain:

```python
        from easybiz.core.kernel import lifecycle

        lifecycle.sync_catalog()
```

- [ ] **Step 6: Run — expect pass; full suite + gate.**

- [ ] **Step 7: Commit**

```bash
git add easybiz/core/kernel/management/commands tests/test_module_commands.py
git commit -m "Add sync_modules and tenant_module commands; init_platform syncs catalog"
```

---

### Task 9: README + milestone close

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update README** — Status: M3a complete (catalog + iam/audit/events models; module-aware migrations; state; lifecycle; capabilities; demo module; `sync_modules`/`tenant_module`; `init_platform` syncs the catalog). Next: M3b (provisioning + tenant ops + `provision_tenant`/`upgrade_modules`). Note provisioning is not yet available (create tenants via tests / M3b).

- [ ] **Step 2: Full gate**

Run: `uv run pytest && uv run ruff check . && uv run ruff format --check . && uv run mypy easybiz config && uv run manage.py makemigrations --check --dry-run`
Expected: all green; `No changes detected`.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "Document M3a module system core in README"
```

---

## M3a Definition of Done

- [ ] Catalog tables in `public`; iam/audit/events tables created per tenant schema; `demo` module ships and loads at startup.
- [ ] Enabling `demo` for one tenant creates `demo_widget` in that schema only — not another tenant's, not `public`; the other schema's `django_migrations` has no `demo` row (Review Focus #1).
- [ ] `enable_module` restores the connection after `migrate_schemas` (I12); `state.is_enabled` works under `schema_context` and `public` → nothing (I13).
- [ ] Enable/disable/remove/re-enable cycle works; guard errors raise `LifecycleError` (already-enabled, unknown, requires-not-enabled, disable-with-dependents, remove-not-disabled).
- [ ] `capabilities.get` gated by enablement; `sync_modules`/`tenant_module` work; `init_platform` syncs the catalog.
- [ ] `uv run pytest` green on real PostgreSQL; `ruff` + `mypy easybiz config` clean; `makemigrations --check` clean; README updated; commits short, no attribution.
