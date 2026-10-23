# Easybiz M3b (Provisioning & Tenant Ops) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Provision a tenant end-to-end (schema, domain, owner user + membership, owner role, enabled modules) as an all-or-nothing operation, plus the tenant lifecycle ops (suspend/resume, add/remove domain, delete) and the `provision_tenant`/`upgrade_modules` CLI.

**Architecture:** `kernel/tenants.py` holds validation (`validate_new_tenant`) and the tenant ops; `kernel/provisioning.py` holds `provision_tenant`, which validates first (creating nothing), then creates the Tenant (schema auto-migrates core apps), the primary Domain, the global owner user + Membership, the `owner` role (`*`) in the tenant schema, an audit row, and enables requested modules in dependency order — rolling the whole thing back (drop schema + delete tenant row) on any failure (I14). All dependencies (users/iam/audit models, `lifecycle`) exist from M1/M3a.

**Tech Stack:** Django 6.1 + django-tenants (`TenantMixin.auto_create_schema`, `tenant_context`), PostgreSQL 16, psycopg 3, pytest; `uv`.

**Spec:** `ERP-CORE-SPEC.md` — provisioning + tenant ops (§6.1), identity/password rule (§6.2), commands (§3.5), data model (§4.1), invariants I14 (all-or-nothing), I12, pitfalls P15 (`DROP SCHEMA IF EXISTS`), P16 (validate before create).

## Scope decision (rulings, user-approved)

- M3b completes M3 (M3a shipped the module system core). Lifecycle `upgrade_modules` already exists (M3a); M3b adds its **CLI**.
- **Forward-dep shim (consistent with M3a):** provisioning creates the owner user via `users.User.objects.create_user` and enforces the ≥10-char password rule inline in `validate_new_tenant`; the polished `users/service.py` (`WeakPassword`) arrives in M4. The `owner` role (`*`) is created directly via the ORM (the `create_role` guard that rejects `*` is the M4 iam service).
- Exceptions live in `tenants.py`: `TenantConflict` (maps to 409 in the M7 platform API) and `TenantValidationError` (422). M4/M7 map them to HTTP; M3b is Python + CLI only.

## Global Constraints

- Python 3.13; Django ≥5.2 (6.1); django-tenants ≥3.8; PostgreSQL 16; `uv`; pytest (DB required).
- **I14:** provisioning is all-or-nothing — validate first (P16, create nothing on failure), and on any later exception drop the schema (`DROP SCHEMA IF EXISTS "<schema>" CASCADE`, P15) and delete the tenant row (cascades domains/memberships/module state). **I12:** reset to public before dropping.
- slug `^[a-z][a-z0-9-]{1,30}$`, not in `{public, platform, admin, api, www}`; schema name `t_<slug with - → _>`; domain lowercased, no scheme/port/path.
- Owner password ≥10 chars unless the owner already has an account.
- §0.5: short commits, no attribution; docstrings on public functions; `ruff` + `mypy easybiz config` clean. Command names unique (`provision_tenant`, `upgrade_modules` — not django-tenants' `create_tenant`).

## Review Focus

- **All-or-nothing (I14):** a failure at any step (bad module enable, domain clash surfacing late, etc.) leaves **no** orphan schema and **no** tenant row. → Task 2.
- **Validate-before-create (P16):** every validation error raises before any row/schema is created. → Task 1.
- **Reserved/duplicate slug + schema collision, domain normalization** (reject `https://`, `host:8000`, `host/path`; lowercase). → Task 1.
- **`delete_tenant` guards:** must be suspended, `confirm_slug` must equal the slug; drops the schema; the owner user (person) survives. → Task 3.
- **`remove_domain`:** refuses the last domain; removing the primary promotes another. → Task 3.

---

### Task 1: `tenants.py` — validation + exceptions

**Files:**
- Create: `easybiz/core/kernel/tenants.py` (validation + helpers this task; ops in Task 3)
- Test: `tests/test_tenant_validation.py`

**Interfaces:**
- Consumes: `tenancy.Tenant/Domain`, `users.User`, `catalog.Module`, `registry`.
- Produces: `TenantError`/`TenantConflict`/`TenantValidationError`; `schema_name_for(slug) -> str`; `normalize_domain(domain) -> str`; `validate_new_tenant(*, slug, domain, owner_email, owner_password, modules) -> str` (returns the normalized domain; raises on any violation, creating nothing).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_tenant_validation.py
import pytest

from easybiz.core.kernel import tenants
from easybiz.core.kernel.tenants import TenantConflict, TenantValidationError


def _validate(**over):
    kw = {
        "slug": "acme",
        "domain": "acme.localhost",
        "owner_email": "owner@acme.test",
        "owner_password": "change-me-now",
        "modules": (),
    }
    kw.update(over)
    return tenants.validate_new_tenant(**kw)


def test_valid_returns_normalized_domain(synced):
    assert _validate(domain="ACME.localhost") == "acme.localhost"


@pytest.mark.parametrize("bad", ["Acme", "1acme", "a", "x" * 32, "ac_me"])
def test_bad_slug_rejected(bad):
    with pytest.raises(TenantValidationError):
        _validate(slug=bad)


@pytest.mark.parametrize("rid", ["public", "platform", "admin", "api", "www"])
def test_reserved_slug_rejected(rid):
    with pytest.raises(TenantValidationError):
        _validate(slug=rid)


@pytest.mark.parametrize("bad", ["https://acme.localhost", "acme.localhost:8000", "acme.localhost/x"])
def test_bad_domain_rejected(bad):
    with pytest.raises(TenantValidationError):
        _validate(domain=bad)


def test_missing_password_for_new_owner_rejected():
    with pytest.raises(TenantValidationError):
        _validate(owner_password=None)


def test_short_password_rejected():
    with pytest.raises(TenantValidationError):
        _validate(owner_password="short")


def test_unknown_module_rejected(synced):
    with pytest.raises(TenantValidationError):
        _validate(modules=("nope",))


def test_module_missing_its_requires_rejected(synced, monkeypatch):
    from easybiz.core.kernel import registry as reg
    from easybiz.core.kernel.manifest import parse_manifest

    # demo now 'requires' timesheets, but only demo is requested
    patched = parse_manifest(
        {"id": "demo", "version": "0.1.0", "requires": [{"module": "timesheets"}]},
        package="easybiz.modules.demo",
    )
    monkeypatch.setitem(reg.registry._manifests, "demo", patched)
    with pytest.raises(TenantValidationError):
        _validate(modules=("demo",))
```

- [ ] **Step 2: Run — expect fail** (`tenants` module missing).

- [ ] **Step 3: Implement `tenants.py` (validation half)**

```python
"""Tenant validation and lifecycle operations (no provisioning — see provisioning.py)."""
from __future__ import annotations

import re

from easybiz.core.catalog.models import Module
from easybiz.core.kernel.registry import registry
from easybiz.core.tenancy.models import Domain, Tenant
from easybiz.core.users.models import User

_SLUG_RE = re.compile(r"^[a-z][a-z0-9-]{1,30}$")
_RESERVED_SLUGS = {"public", "platform", "admin", "api", "www"}


class TenantError(Exception):
    """Base class for tenant operation failures."""


class TenantConflict(TenantError):
    """A uniqueness/state conflict (maps to HTTP 409)."""


class TenantValidationError(TenantError):
    """Invalid input (maps to HTTP 422)."""


def schema_name_for(slug: str) -> str:
    return "t_" + slug.replace("-", "_")


def normalize_domain(domain: str) -> str:
    d = (domain or "").strip().lower()
    if not d or "://" in d or "/" in d or ":" in d or " " in d:
        raise TenantValidationError(f"invalid domain {domain!r}")
    return d


def validate_new_tenant(*, slug, domain, owner_email, owner_password, modules) -> str:
    """Validate a provisioning request, creating nothing. Returns the normalized domain."""
    if not _SLUG_RE.match(slug):
        raise TenantValidationError(f"invalid slug {slug!r}")
    if slug in _RESERVED_SLUGS:
        raise TenantValidationError(f"reserved slug {slug!r}")
    schema = schema_name_for(slug)
    if Tenant.objects.filter(slug=slug).exists() or Tenant.objects.filter(schema_name=schema).exists():
        raise TenantConflict(f"slug {slug!r} is already in use")

    domain_norm = normalize_domain(domain)
    if Domain.objects.filter(domain=domain_norm).exists():
        raise TenantConflict(f"domain {domain_norm!r} is already in use")

    owner = User.objects.filter(email=owner_email.lower()).first()
    if owner is None and (not owner_password or len(owner_password) < 10):
        raise TenantValidationError("owner password must be at least 10 characters")

    requested = set(modules)
    for mid in requested:
        if not Module.objects.filter(id=mid).exists():
            raise TenantValidationError(f"unknown module {mid!r}")
        manifest = registry.manifest(mid)
        if manifest:
            for dep, _ in manifest.requires:
                if dep not in requested:
                    raise TenantValidationError(
                        f"module {mid!r} requires {dep!r} in the same request"
                    )
    return domain_norm
```

- [ ] **Step 4: Run — expect pass; then `ruff`/`mypy` clean.**

- [ ] **Step 5: Commit**

```bash
git add easybiz/core/kernel/tenants.py tests/test_tenant_validation.py
git commit -m "Add tenant request validation"
```

---

### Task 2: `provisioning.py` — all-or-nothing provision

**Files:**
- Create: `easybiz/core/kernel/provisioning.py`
- Modify: `tests/conftest.py` (add a `provision` fixture that cleans up created tenants)
- Test: `tests/test_provisioning.py`

**Interfaces:**
- Consumes: `validate_new_tenant`/`schema_name_for`, `Tenant/Domain`, `User/Membership`, `Role/RolePermission/UserRole`, `AuditLog`, `lifecycle.enable_module`, `registry.load_order`.
- Produces: `provision_tenant(name, slug, domain, owner_email, owner_password=None, modules=(), actor_id=None) -> Tenant`.

- [ ] **Step 1: Add the `provision` fixture to `tests/conftest.py`**

```python
@pytest.fixture
def provision():
    created: list[tuple[str, str]] = []  # (schema_name, owner_email)

    def _provision(slug="acme", modules=(), **over):
        from easybiz.core.kernel import provisioning

        params = {
            "name": slug.title(),
            "slug": slug,
            "domain": f"{slug}.localhost",
            "owner_email": f"owner@{slug}.test",
            "owner_password": "change-me-now",
            "modules": modules,
        }
        params.update(over)
        tenant = provisioning.provision_tenant(**params)
        created.append((tenant.schema_name, params["owner_email"]))
        return tenant

    yield _provision

    from easybiz.core.tenancy.models import Tenant
    from easybiz.core.users.models import User

    connection.set_schema_to_public()
    for schema, email in created:
        with connection.cursor() as cur:
            cur.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        Tenant.objects.filter(schema_name=schema).delete()
        User.objects.filter(email=email).delete()
```

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_provisioning.py
import pytest
from django_tenants.utils import tenant_context

from easybiz.core.iam.models import Role, UserRole
from easybiz.core.kernel import provisioning, state
from easybiz.core.kernel.tenants import TenantConflict
from easybiz.core.tenancy.models import Domain, Tenant
from easybiz.core.users.models import Membership, User


def test_provision_creates_everything(synced, provision, tables_in):
    tenant = provision(slug="acme", modules=("demo",))
    assert Tenant.objects.filter(slug="acme").exists()
    assert Domain.objects.get(tenant=tenant).is_primary is True
    owner = User.objects.get(email="owner@acme.test")
    assert Membership.objects.filter(user=owner, tenant=tenant).exists()
    assert state.is_enabled(tenant, "demo") is True
    assert "demo_widget" in tables_in(tenant.schema_name)
    with tenant_context(tenant):
        owner_role = Role.objects.get(name="owner")
        assert owner_role.permissions.filter(permission="*").exists()
        assert UserRole.objects.filter(user_id=owner.id, role=owner_role).exists()


def test_two_tenants_are_isolated(synced, provision, tables_in):
    a = provision(slug="acme", modules=("demo",))
    b = provision(slug="zenith", modules=())
    assert "demo_widget" in tables_in(a.schema_name)
    assert "demo_widget" not in tables_in(b.schema_name)


def test_duplicate_slug_conflicts(synced, provision):
    provision(slug="acme")
    with pytest.raises(TenantConflict):
        provision(slug="acme", domain="acme2.localhost", owner_email="o2@acme.test")


def test_rollback_leaves_no_orphan(synced, monkeypatch, tables_in):
    from easybiz.core.kernel import lifecycle

    def _boom(*a, **k):
        raise RuntimeError("enable failed")

    monkeypatch.setattr(lifecycle, "enable_module", _boom)
    with pytest.raises(RuntimeError):
        provisioning.provision_tenant(
            name="Acme", slug="acme", domain="acme.localhost",
            owner_email="owner@acme.test", owner_password="change-me-now", modules=("demo",),
        )
    assert not Tenant.objects.filter(slug="acme").exists()
    assert "t_acme" not in {r[0] for r in _all_schemas()}


def _all_schemas():
    from django.db import connection

    with connection.cursor() as cur:
        cur.execute("SELECT schema_name FROM information_schema.schemata")
        return cur.fetchall()
```

- [ ] **Step 3: Run — expect fail** (`provisioning` missing).

- [ ] **Step 4: Implement `provisioning.py`**

```python
"""All-or-nothing tenant provisioning (I14)."""
from __future__ import annotations

from django.db import connection, transaction
from django_tenants.utils import tenant_context

from easybiz.core.audit.models import AuditLog
from easybiz.core.iam.models import Role, RolePermission, UserRole
from easybiz.core.kernel import lifecycle
from easybiz.core.kernel.registry import registry
from easybiz.core.kernel.tenants import schema_name_for, validate_new_tenant
from easybiz.core.tenancy.models import Domain, Tenant
from easybiz.core.users.models import Membership, User


def provision_tenant(
    name, slug, domain, owner_email, owner_password=None, modules=(), actor_id=None
) -> Tenant:
    """Create a tenant end to end, or roll everything back on any failure (I14)."""
    domain_norm = validate_new_tenant(
        slug=slug,
        domain=domain,
        owner_email=owner_email,
        owner_password=owner_password,
        modules=modules,
    )
    schema = schema_name_for(slug)
    tenant: Tenant | None = None
    try:
        tenant = Tenant(schema_name=schema, slug=slug, name=name)
        tenant.save()  # creates the schema and migrates core tenant apps
        Domain.objects.create(domain=domain_norm, tenant=tenant, is_primary=True)

        owner = User.objects.filter(email=owner_email.lower()).first()
        if owner is None:
            owner = User.objects.create_user(email=owner_email, password=owner_password)
        Membership.objects.get_or_create(user=owner, tenant=tenant, defaults={"is_active": True})

        with tenant_context(tenant), transaction.atomic():
            role, _ = Role.objects.get_or_create(
                name="owner", defaults={"description": "Tenant owner", "is_system": True}
            )
            RolePermission.objects.get_or_create(role=role, permission="*")
            UserRole.objects.get_or_create(user_id=owner.id, role=role)
            AuditLog.objects.create(
                actor_id=actor_id, action="tenant.provisioned", entity="tenant", entity_id=slug
            )

        for module_id in [m for m in registry.load_order() if m in set(modules)]:
            lifecycle.enable_module(tenant, module_id, actor_id=actor_id)
        return tenant
    except Exception:
        connection.set_schema_to_public()
        with connection.cursor() as cur:
            cur.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        if tenant is not None and tenant.pk:
            Tenant.objects.filter(pk=tenant.pk).delete()
        raise
```

- [ ] **Step 5: Run — expect pass; full suite + gate.**

- [ ] **Step 6: Commit**

```bash
git add easybiz/core/kernel/provisioning.py tests/test_provisioning.py tests/conftest.py
git commit -m "Add all-or-nothing tenant provisioning"
```

---

### Task 3: `tenants.py` — suspend/resume, domains, delete

**Files:**
- Modify: `easybiz/core/kernel/tenants.py`
- Test: `tests/test_tenant_ops.py`

**Interfaces:**
- Produces: `suspend(tenant)`, `resume(tenant)`, `add_domain(tenant, domain, is_primary=False) -> Domain`, `remove_domain(tenant, domain)`, `delete_tenant(tenant, confirm_slug)`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_tenant_ops.py
import pytest

from easybiz.core.kernel import tenants
from easybiz.core.kernel.tenants import TenantConflict, TenantValidationError
from easybiz.core.tenancy.models import Domain, Tenant


def test_suspend_resume(synced, provision):
    tenant = provision(slug="acme")
    tenants.suspend(tenant)
    assert Tenant.objects.get(pk=tenant.pk).is_active is False
    with pytest.raises(TenantConflict):
        tenants.suspend(tenant)
    tenants.resume(tenant)
    assert Tenant.objects.get(pk=tenant.pk).is_active is True


def test_add_domain_and_primary_switch(synced, provision):
    tenant = provision(slug="acme")
    tenants.add_domain(tenant, "ACME.example", is_primary=True)
    assert Domain.objects.get(tenant=tenant, domain="acme.example").is_primary is True
    assert Domain.objects.get(tenant=tenant, domain="acme.localhost").is_primary is False
    with pytest.raises(TenantConflict):
        tenants.add_domain(tenant, "acme.example")


def test_remove_domain_keeps_at_least_one_and_promotes(synced, provision):
    tenant = provision(slug="acme")
    tenants.add_domain(tenant, "acme.example")
    tenants.remove_domain(tenant, "acme.localhost")  # removing the primary
    assert tenant.domains.count() == 1
    assert Domain.objects.get(tenant=tenant, domain="acme.example").is_primary is True
    with pytest.raises(TenantConflict):
        tenants.remove_domain(tenant, "acme.example")  # last one


def test_delete_requires_suspended_and_confirmation(synced, provision):
    tenant = provision(slug="acme")
    with pytest.raises(TenantConflict):
        tenants.delete_tenant(tenant, "acme")  # not suspended
    tenants.suspend(tenant)
    with pytest.raises(TenantValidationError):
        tenants.delete_tenant(tenant, "wrong")
    schema = tenant.schema_name
    tenants.delete_tenant(tenant, "acme")
    assert not Tenant.objects.filter(slug="acme").exists()
```

- [ ] **Step 2: Run — expect fail.**

- [ ] **Step 3: Implement the ops in `tenants.py`**

```python
# appended to tenants.py
from django.db import connection  # add to the imports at top


def suspend(tenant) -> None:
    if not tenant.is_active:
        raise TenantConflict("tenant is already suspended")
    tenant.is_active = False
    tenant.save(update_fields=["is_active"])


def resume(tenant) -> None:
    if tenant.is_active:
        raise TenantConflict("tenant is already active")
    tenant.is_active = True
    tenant.save(update_fields=["is_active"])


def add_domain(tenant, domain, is_primary: bool = False) -> Domain:
    d = normalize_domain(domain)
    if Domain.objects.filter(domain=d).exists():
        raise TenantConflict(f"domain {d!r} is already in use")
    return Domain.objects.create(domain=d, tenant=tenant, is_primary=is_primary)


def remove_domain(tenant, domain) -> None:
    d = normalize_domain(domain)
    row = Domain.objects.filter(tenant=tenant, domain=d).first()
    if row is None:
        raise TenantValidationError(f"{d!r} is not a domain of this tenant")
    if tenant.domains.count() <= 1:
        raise TenantConflict("a tenant must keep at least one domain")
    was_primary = row.is_primary
    row.delete()
    if was_primary:
        promoted = tenant.domains.first()
        promoted.is_primary = True
        promoted.save(update_fields=["is_primary"])


def delete_tenant(tenant, confirm_slug: str) -> None:
    if tenant.is_active:
        raise TenantConflict("tenant must be suspended before deletion")
    if confirm_slug != tenant.slug:
        raise TenantValidationError("confirm_slug does not match the tenant slug")
    schema = tenant.schema_name
    connection.set_schema_to_public()
    with connection.cursor() as cur:
        cur.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
    tenant.delete()  # people (users) are kept; memberships cascade
```

Note: `DomainMixin.save` already demotes other primaries when a primary is saved, so `add_domain(..., is_primary=True)` auto-demotes `acme.localhost` (verify in the test; if the library does not, demote explicitly — library wins).

- [ ] **Step 4: Run — expect pass; full suite + gate.**

- [ ] **Step 5: Commit**

```bash
git add easybiz/core/kernel/tenants.py tests/test_tenant_ops.py
git commit -m "Add tenant suspend/resume, domain, and delete operations"
```

---

### Task 4: CLI — `provision_tenant` and `upgrade_modules`

**Files:**
- Create: `easybiz/core/kernel/management/commands/provision_tenant.py`, `easybiz/core/kernel/management/commands/upgrade_modules.py`
- Test: `tests/test_provision_commands.py`

**Interfaces:**
- Produces: `provision_tenant <slug> --domain --owner-email --owner-password [--name] [--modules a,b]`; `upgrade_modules` (calls `lifecycle.upgrade_modules`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_provision_commands.py
from django.core.management import call_command

from easybiz.core.kernel import state
from easybiz.core.tenancy.models import Tenant


def test_provision_tenant_command(synced, request):
    def _cleanup():
        from django.db import connection

        connection.set_schema_to_public()
        with connection.cursor() as cur:
            cur.execute('DROP SCHEMA IF EXISTS "t_cli" CASCADE')
        Tenant.objects.filter(slug="cli").delete()

    request.addfinalizer(_cleanup)
    call_command(
        "provision_tenant", "cli",
        "--domain", "cli.localhost",
        "--owner-email", "owner@cli.test",
        "--owner-password", "change-me-now",
        "--modules", "demo",
        verbosity=0,
    )
    tenant = Tenant.objects.get(slug="cli")
    assert state.is_enabled(tenant, "demo") is True
```

- [ ] **Step 2: Run — expect fail.**

- [ ] **Step 3: Implement `provision_tenant.py`**

```python
from django.core.management.base import BaseCommand, CommandError

from easybiz.core.kernel import provisioning
from easybiz.core.kernel.tenants import TenantError


class Command(BaseCommand):
    """Create a tenant end to end."""

    def add_arguments(self, parser) -> None:
        parser.add_argument("slug")
        parser.add_argument("--domain", required=True)
        parser.add_argument("--owner-email", required=True)
        parser.add_argument("--owner-password")
        parser.add_argument("--name")
        parser.add_argument("--modules", default="")

    def handle(self, *args, **options) -> None:
        modules = tuple(m for m in options["modules"].split(",") if m)
        try:
            tenant = provisioning.provision_tenant(
                name=options["name"] or options["slug"].title(),
                slug=options["slug"],
                domain=options["domain"],
                owner_email=options["owner_email"],
                owner_password=options["owner_password"],
                modules=modules,
            )
        except TenantError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(f"provisioned tenant {tenant.slug!r} ({tenant.schema_name})")
```

- [ ] **Step 4: Implement `upgrade_modules.py`**

```python
from django.core.management.base import BaseCommand

from easybiz.core.kernel import lifecycle


class Command(BaseCommand):
    """Refresh the catalog, migrate every schema, and record module versions."""

    def handle(self, *args, **options) -> None:
        order = lifecycle.upgrade_modules()
        self.stdout.write(f"upgraded: {', '.join(order)}")
```

- [ ] **Step 5: Run — expect pass; full suite + gate.**

- [ ] **Step 6: Commit**

```bash
git add easybiz/core/kernel/management/commands tests/test_provision_commands.py
git commit -m "Add provision_tenant and upgrade_modules commands"
```

---

### Task 5: README + milestone close

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update README** — Status: **M3 complete** (M3a module system core + M3b provisioning). Tenants are provisioned end to end (all-or-nothing), suspended/resumed, re-domained, and deleted; `provision_tenant`/`upgrade_modules` CLI exist. Add the two commands to the command list. Next: **M4** (AuthN/AuthZ, audit + iam services, tenant API, middleware activation).

- [ ] **Step 2: Full gate**

Run: `uv run pytest && uv run ruff check . && uv run ruff format --check . && uv run mypy easybiz config && uv run manage.py makemigrations --check --dry-run`
Expected: all green; `No changes detected` (M3b adds no models).

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "Document M3 provisioning and tenant ops in README"
```

---

## M3b Definition of Done

- [ ] `provision_tenant` creates schema + primary domain + owner user/membership + `owner` role (`*`) + audit + enabled modules; two tenants are isolated.
- [ ] Any failure rolls back fully — no orphan schema, no tenant row (I14); validation creates nothing (P16).
- [ ] suspend/resume (409 if already in state); add_domain (409 dup, normalized); remove_domain (keeps ≥1, promotes primary); delete_tenant (suspended + `confirm_slug`, drops schema, people kept).
- [ ] `provision_tenant`/`upgrade_modules` CLI work.
- [ ] `uv run pytest` green on real PostgreSQL; `ruff` + `mypy easybiz config` clean; `makemigrations --check` clean; README updated; commits short, no attribution.
