# Easybiz M4 (Authentication, Authorization, Audit & Tenant API) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the tenant API real and authenticated end to end: core-permission catalogue, the identity/authz/audit services, JWT login + `/auth/me`, the `TenantJWTAuth`/`perm()` guard, the activated tenant-status + module-gate middleware, Swagger docs, and the full `/core/*` resource endpoints (modules, roles, users, audit).

**Architecture:** `users/service.authenticate` checks credentials + active membership; `iam/service` computes a user's permissions (union of role codes) and matches them (wildcards); `audit/service.record` writes tenant audit rows. `api/auth.py` encodes/validates HS256 JWTs: `TenantJWTAuth` (a Ninja `HttpBearer`) validates signature/expiry/tenant/active-membership and, for `perm("code")`, the permission; `/auth/login` and `/auth/me` live on a mounted `NinjaAPI`. The two stub middlewares from M0 become real (suspended tenant → 403, disabled module route → 404).

**Tech Stack:** Django 6.1 + django-tenants, django-ninja (`NinjaAPI`, `Router`, `HttpBearer`, `HttpError`), PyJWT (HS256), PostgreSQL 16, pytest; `uv`.

**Spec:** `ERP-CORE-SPEC.md` — identity/auth (§6.2), authorization (§6.3), audit (§6.4), middleware (§5.7), API docs (§6.6), tenant API (§7.1 `/auth/*` rows), permission catalogue (Appendix C core set), invariants I8/I9/I10.

## Scope decision (rulings)

- **Single M4 milestone** (user chose to merge the earlier a/b split): Tasks 1–6 build the auth engine + services + `/auth` + middleware + docs; Tasks 7–12 add the `/core/*` resource endpoints and the role/user management services.
- **Gap fixed here:** M3a's `sync_catalog` never upserted the **core permissions** (§5.6). Task 1 adds `kernel/core_permissions.py` and makes `sync_catalog` upsert them (`module=null`) — needed before authz/role management.
- **Refactor onto services:** `audit/service.record` is added and the direct `AuditLog.objects.create(...)` calls in `lifecycle.py`/`provisioning.py` are switched to it (the M3 "write to models directly" shim resolves here). Behaviour unchanged.
- **Forward-dep shim (consistent with M3):** `DELETE /core/users/{id}` must publish `core.membership.removed`, but `events/service.publish` is **M5** — Task 11 writes the `OutboxEvent` row directly (as lifecycle did in M3a); M5 refactors it onto the service.
- **Multiple auth methods (2FA, magic link, PIN, social/OIDC/SSO, refresh tokens) are deferred to F13** — the design is additive (identity decoupled from credentials, membership orthogonal to auth, centralized token issuance), so no seams are reserved now.
- Platform auth (`PlatformJWTAuth`, platform login throttle) is **M7**, not here.

## Global Constraints

- Python 3.13; Django ≥5.2 (6.1); django-tenants ≥3.8; django-ninja ≥1.7; PyJWT HS256 with `SECRET_KEY`; PostgreSQL 16; `uv`; pytest (DB required).
- **I9:** tenant tokens bind to the host's tenant (`tenant` claim == `request.tenant.schema_name`); the tenant API returns 401 on the public host. **I8:** permission codes `<module>.<action>`; core codes start with `core.`. **I10:** sensitive actions write an audit row.
- Errors: JSON `{"detail": "..."}`; 401 unauthenticated, 403 `Missing permission <code>`, 404 module not enabled / not found, 403 suspended.
- Types live in `types.py` (Ninja schemas), not in `api/auth.py` (§0.5). Docstrings on public functions; `ruff` + `mypy easybiz config` clean.

## Review Focus

- **Cross-tenant token rejection (I9):** a token minted for tenant A must be refused by tenant B (tenant-claim mismatch). The tenant API is not mounted on the public host, so `/api/*` there is 404 (§2.5); `TenantJWTAuth` also defensively returns 401 if ever invoked on the public schema. → Task 5.
- **Uniform login failure:** wrong password, unknown email, and no-membership all return the same 401 `Invalid credentials` (no account enumeration). → Task 5.
- **Permission wildcard matching:** `*`, exact code, and `module.*` prefix all grant; an unrelated `other.*` does not. → Task 4.
- **Module gate vs non-module paths:** `/api/<enabled>/…` and `/api/auth/*` pass; `/api/<installed-but-disabled>/…` → 404 with the gate message; a path whose first segment isn't an installed module is untouched. → Task 6.
- **Suspended tenant:** every path returns 403 while `is_active=False`, including before auth. → Task 6.
- **`create_role` guards:** rejects `*`, unknown/disabled permissions, and duplicate names (422). → Task 7.
- **New-account rule on `POST /core/users`:** a new email with no password → 422; a weak password → 422; an existing user is reused. → Tasks 8, 11.
- **Self-deletion guard:** `DELETE /core/users/{id}` refuses to remove the caller (409) and publishes `core.membership.removed`. → Task 11.
- **Module object `blocked_by`:** lists missing hard deps (can't enable) or enabled dependents (can't disable). → Task 9.

---

### Task 1: Core permission catalogue + `sync_catalog` upsert

**Files:**
- Create: `easybiz/core/kernel/core_permissions.py`
- Modify: `easybiz/core/kernel/lifecycle.py` (`sync_catalog` upserts core perms)
- Test: `tests/test_core_permissions.py`

**Interfaces:**
- Produces: `CORE_PERMISSIONS: list[tuple[str, str]]` (code, description); `sync_catalog()` now upserts them with `module=None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_core_permissions.py
from easybiz.core.catalog.models import Permission
from easybiz.core.kernel import lifecycle


def test_sync_catalog_upserts_core_permissions(synced):
    lifecycle.sync_catalog()
    codes = set(Permission.objects.filter(module__isnull=True).values_list("code", flat=True))
    assert {
        "core.module.read", "core.module.manage",
        "core.role.read", "core.role.manage",
        "core.user.read", "core.user.manage",
        "core.audit.read",
    } <= codes
```

- [ ] **Step 2: Run — expect fail.**

- [ ] **Step 3: Write `core_permissions.py`**

```python
"""The core (non-module) permission catalogue, synced with module permissions."""

CORE_PERMISSIONS: list[tuple[str, str]] = [
    ("core.module.read", "See modules and their status"),
    ("core.module.manage", "Enable, disable, and remove modules"),
    ("core.role.read", "See roles"),
    ("core.role.manage", "Create and edit roles"),
    ("core.user.read", "See users and their roles"),
    ("core.user.manage", "Add, remove, and assign roles to users"),
    ("core.audit.read", "Read the tenant audit log"),
]
```

- [ ] **Step 4: Upsert in `sync_catalog`** (lifecycle.py)

```python
def sync_catalog() -> list[str]:
    from easybiz.core.kernel.core_permissions import CORE_PERMISSIONS

    for code, desc in CORE_PERMISSIONS:
        Permission.objects.update_or_create(
            code=code, defaults={"module": None, "description": desc}
        )
    order = registry.load_order()
    for module_id in order:
        install_module(module_id)
    return order
```

- [ ] **Step 5: Run — expect pass; gate; commit.**

```bash
git add easybiz/core/kernel/core_permissions.py easybiz/core/kernel/lifecycle.py tests/test_core_permissions.py
git commit -m "Add core permission catalogue and sync it"
```

---

### Task 2: `audit/service.record` + refactor direct writes

**Files:**
- Create: `easybiz/core/audit/service.py`
- Modify: `easybiz/core/kernel/lifecycle.py`, `easybiz/core/kernel/provisioning.py` (use `audit.record`)
- Test: `tests/test_audit_service.py`

**Interfaces:**
- Produces: `record(actor_id, action, entity="", entity_id="", before=None, after=None) -> AuditLog` — writes in the current tenant schema/transaction.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_audit_service.py
from django_tenants.utils import tenant_context

from easybiz.core.audit.models import AuditLog
from easybiz.core.audit import service as audit


def test_record_writes_in_tenant_schema(synced, db_tenant):
    with tenant_context(db_tenant):
        audit.record(actor_id=None, action="thing.done", entity="thing", entity_id="1")
        assert AuditLog.objects.filter(action="thing.done", entity_id="1").exists()
```

- [ ] **Step 2: Run — expect fail.**

- [ ] **Step 3: Implement `audit/service.py`**

```python
"""Tenant audit log writer (writes in the caller's schema and transaction)."""
from __future__ import annotations

from uuid import UUID

from easybiz.core.audit.models import AuditLog


def record(
    actor_id: UUID | None,
    action: str,
    entity: str = "",
    entity_id: str = "",
    before: dict | None = None,
    after: dict | None = None,
) -> AuditLog:
    return AuditLog.objects.create(
        actor_id=actor_id,
        action=action,
        entity=entity,
        entity_id=entity_id,
        before=before,
        after=after,
    )
```

- [ ] **Step 4: Refactor** the three `AuditLog.objects.create(...)` sites in `lifecycle.py` (module.enabled/disabled/data_removed) and the one in `provisioning.py` (tenant.provisioned) to call `audit.record(...)`. Import `from easybiz.core.audit import service as audit`. Keep the same field values.

- [ ] **Step 5: Run — expect pass; full suite stays green (lifecycle/provisioning tests unchanged); gate; commit.**

```bash
git add easybiz/core/audit/service.py easybiz/core/kernel/lifecycle.py easybiz/core/kernel/provisioning.py tests/test_audit_service.py
git commit -m "Add audit service and route lifecycle/provisioning writes through it"
```

---

### Task 3: `users/service.authenticate`

**Files:**
- Create: `easybiz/core/users/service.py`
- Test: `tests/test_users_service.py`

**Interfaces:**
- Produces: `authenticate(email, password, tenant) -> User | None` — valid credentials AND an active membership of `tenant`, else `None` (uniform failure).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_users_service.py
from easybiz.core.users import service as users
from easybiz.core.users.models import Membership, User


def test_authenticate_requires_credentials_and_membership(synced, provision):
    tenant = provision(slug="acme")  # owner@acme.test / change-me-now, member of acme
    owner = User.objects.get(email="owner@acme.test")
    assert users.authenticate("owner@acme.test", "change-me-now", tenant) == owner
    assert users.authenticate("owner@acme.test", "wrong", tenant) is None
    assert users.authenticate("nobody@acme.test", "change-me-now", tenant) is None

    other = provision(slug="zenith")  # different tenant
    assert users.authenticate("owner@acme.test", "change-me-now", other) is None  # no membership
```

- [ ] **Step 2: Run — expect fail.**

- [ ] **Step 3: Implement `users/service.py`**

```python
"""Authentication against the global user directory + per-tenant membership."""
from __future__ import annotations

from easybiz.core.users.models import Membership, User


def authenticate(email: str, password: str, tenant) -> User | None:
    user = User.objects.filter(email=email.lower(), is_active=True).first()
    if user is None or not user.check_password(password):
        return None
    if not Membership.objects.filter(user=user, tenant=tenant, is_active=True).exists():
        return None
    return user
```

- [ ] **Step 4: Run — expect pass; gate; commit.**

```bash
git add easybiz/core/users/service.py tests/test_users_service.py
git commit -m "Add user authentication service"
```

---

### Task 4: `iam/service` — permissions, wildcard check, menu

**Files:**
- Create: `easybiz/core/iam/service.py`
- Test: `tests/test_iam_service.py`

**Interfaces:**
- Produces: `permissions_for(user_id) -> set[str]` (union of the user's role codes in the current schema); `has_permission(perms, code) -> bool` (`*` / exact / `module.*`); `menu_for(tenant, perms) -> list[dict]` (from enabled modules' manifests, filtered).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_iam_service.py
from django_tenants.utils import tenant_context

from easybiz.core.iam import service as iam
from easybiz.core.iam.models import Role, RolePermission, UserRole


def test_has_permission_wildcards():
    assert iam.has_permission({"*"}, "core.module.read")
    assert iam.has_permission({"core.module.read"}, "core.module.read")
    assert iam.has_permission({"core.*"}, "core.module.read")
    assert not iam.has_permission({"other.*"}, "core.module.read")
    assert not iam.has_permission(set(), "core.module.read")


def test_permissions_for_unions_roles(synced, db_tenant):
    import uuid

    uid = uuid.uuid4()
    with tenant_context(db_tenant):
        r1 = Role.objects.create(name="a")
        r2 = Role.objects.create(name="b")
        RolePermission.objects.create(role=r1, permission="core.module.read")
        RolePermission.objects.create(role=r2, permission="demo.widget.read")
        UserRole.objects.create(user_id=uid, role=r1)
        UserRole.objects.create(user_id=uid, role=r2)
        assert iam.permissions_for(uid) == {"core.module.read", "demo.widget.read"}


def test_menu_for_filters_by_permission(synced, db_tenant):
    from easybiz.core.kernel import lifecycle

    lifecycle.enable_module(db_tenant, "demo")  # demo manifest menu is empty -> []
    with tenant_context(db_tenant):
        assert iam.menu_for(db_tenant, {"*"}) == []
```

- [ ] **Step 2: Run — expect fail.**

- [ ] **Step 3: Implement `iam/service.py`**

```python
"""Authorization helpers: a user's effective permissions, wildcard checks, menu."""
from __future__ import annotations

from easybiz.core.iam.models import RolePermission, UserRole
from easybiz.core.kernel import state
from easybiz.core.kernel.registry import registry


def permissions_for(user_id) -> set[str]:
    role_ids = UserRole.objects.filter(user_id=user_id).values_list("role_id", flat=True)
    return set(
        RolePermission.objects.filter(role_id__in=role_ids).values_list("permission", flat=True)
    )


def has_permission(perms: set[str], code: str) -> bool:
    if "*" in perms or code in perms:
        return True
    return f"{code.split('.')[0]}.*" in perms


def menu_for(tenant, perms: set[str]) -> list[dict]:
    items: list[dict] = []
    for module_id in sorted(state.enabled_module_ids(tenant)):
        manifest = registry.manifest(module_id)
        for item in manifest.menu if manifest else []:
            needed = item.get("permission")
            if needed is None or has_permission(perms, needed):
                items.append({"module": module_id, "label": item["label"], "route": item["route"]})
    return items
```

- [ ] **Step 4: Run — expect pass; gate; commit.**

```bash
git add easybiz/core/iam/service.py tests/test_iam_service.py
git commit -m "Add iam authorization service"
```

---

### Task 5: JWT auth, `/auth/login`, `/auth/me`, mounted Ninja API + docs

**Files:**
- Create: `easybiz/core/api/types.py`, `easybiz/core/api/auth.py`, `easybiz/core/api/__init__.py` (NinjaAPI instance)
- Modify: `config/urls.py`
- Test: `tests/test_auth_api.py`

**Interfaces:**
- Produces: `encode_tenant_token(user_id, schema_name) -> str`, `decode_token(token) -> dict`; `TenantJWTAuth(HttpBearer)`; `perm(code) -> TenantJWTAuth`; `authenticated = TenantJWTAuth()`; `api` (NinjaAPI, `urls_namespace="easybiz"`) with the auth router; mounted at `/api/`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_auth_api.py
from django.test import Client


def _login(host, email, password):
    return Client().post(
        "/api/auth/login", data={"email": email, "password": password},
        content_type="application/json", HTTP_HOST=host,
    )


def test_login_and_me(synced, provision):
    provision(slug="acme")
    resp = _login("acme.localhost", "owner@acme.test", "change-me-now")
    assert resp.status_code == 200
    token = resp.json()["access_token"]
    me = Client().get("/api/auth/me", HTTP_HOST="acme.localhost", HTTP_AUTHORIZATION=f"Bearer {token}")
    assert me.status_code == 200
    body = me.json()
    assert body["email"] == "owner@acme.test"
    assert "*" in body["permissions"]  # owner role


def test_uniform_login_failure(synced, provision):
    provision(slug="acme")
    for email, pw in [("owner@acme.test", "wrong"), ("nobody@acme.test", "change-me-now")]:
        resp = _login("acme.localhost", email, pw)
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Invalid credentials"


def test_token_rejected_by_other_tenant(synced, provision):
    provision(slug="acme")
    provision(slug="zenith")
    token = _login("acme.localhost", "owner@acme.test", "change-me-now").json()["access_token"]
    me = Client().get("/api/auth/me", HTTP_HOST="zenith.localhost", HTTP_AUTHORIZATION=f"Bearer {token}")
    assert me.status_code == 401


def test_tenant_api_absent_on_public_host(synced):
    # the public host serves urls_public (health only); /api/* is not mounted there
    assert Client().get("/api/auth/me", HTTP_HOST="localhost").status_code == 404
```

- [ ] **Step 2: Run — expect fail.**

- [ ] **Step 3: Write `api/types.py`**

```python
"""Ninja request/response schemas for the tenant API."""
from ninja import Schema


class LoginIn(Schema):
    email: str
    password: str


class TokenOut(Schema):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class MenuItemOut(Schema):
    module: str
    label: str
    route: str


class MeOut(Schema):
    id: str
    email: str
    permissions: list[str]
    enabled_modules: list[str]
    menu: list[MenuItemOut]
```

- [ ] **Step 4: Write `api/auth.py`**

```python
"""Tenant JWT auth, the `perm()` guard, and the /auth endpoints."""
from __future__ import annotations

import time

import jwt
from django.conf import settings
from django_tenants.utils import get_public_schema_name
from ninja import Router
from ninja.errors import HttpError
from ninja.security import HttpBearer

from easybiz.core.api.types import LoginIn, MeOut, TokenOut
from easybiz.core.iam import service as iam
from easybiz.core.kernel import state
from easybiz.core.users import service as users
from easybiz.core.users.models import Membership, User


def encode_tenant_token(user_id, schema_name: str) -> str:
    now = int(time.time())
    payload = {
        "sub": str(user_id),
        "tenant": schema_name,
        "iat": now,
        "exp": now + settings.EASYBIZ_JWT_TTL_SECONDS,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")


def decode_token(token: str) -> dict:
    return jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])


class TenantJWTAuth(HttpBearer):
    """Validate a tenant token (I9) and, when given, an endpoint permission."""

    def __init__(self, permission: str | None = None) -> None:
        self.permission = permission
        super().__init__()

    def authenticate(self, request, token):
        tenant = getattr(request, "tenant", None)
        if tenant is None or tenant.schema_name == get_public_schema_name():
            return None
        try:
            payload = decode_token(token)
        except jwt.PyJWTError:
            return None
        if payload.get("tenant") != tenant.schema_name:
            return None
        user = User.objects.filter(id=payload.get("sub"), is_active=True).first()
        if user is None:
            return None
        if not Membership.objects.filter(user=user, tenant=tenant, is_active=True).exists():
            return None
        if self.permission is not None:
            perms = iam.permissions_for(user.id)
            if not iam.has_permission(perms, self.permission):
                raise HttpError(403, f"Missing permission {self.permission}")
        return user


def perm(code: str) -> TenantJWTAuth:
    return TenantJWTAuth(permission=code)


authenticated = TenantJWTAuth()

router = Router()


@router.post("/login", auth=None, response=TokenOut)
def login(request, data: LoginIn):
    """Exchange tenant credentials for a tenant access token."""
    user = users.authenticate(data.email, data.password, request.tenant)
    if user is None:
        raise HttpError(401, "Invalid credentials")
    return TokenOut(
        access_token=encode_tenant_token(user.id, request.tenant.schema_name),
        expires_in=settings.EASYBIZ_JWT_TTL_SECONDS,
    )


@router.get("/me", auth=authenticated, response=MeOut)
def me(request):
    """The caller's identity, effective permissions, enabled modules, and menu."""
    user = request.auth
    perms = iam.permissions_for(user.id)
    return MeOut(
        id=str(user.id),
        email=user.email,
        permissions=sorted(perms),
        enabled_modules=sorted(state.enabled_module_ids(request.tenant)),
        menu=iam.menu_for(request.tenant, perms),
    )
```

- [ ] **Step 5: Write `api/__init__.py` (NinjaAPI instance)**

```python
from ninja import NinjaAPI

from easybiz.core.api.auth import router as auth_router

api = NinjaAPI(urls_namespace="easybiz", title="Easybiz Tenant API")
api.add_router("/auth", auth_router)
```

- [ ] **Step 6: Mount in `config/urls.py`**

```python
"""Tenant host URLs."""
from django.urls import path

from easybiz.core.api import api

urlpatterns = [path("api/", api.urls)]
```

- [ ] **Step 7: Run the auth tests — expect pass**

Run: `uv run pytest tests/test_auth_api.py -v`
Expected: PASS. Confirm `/api/docs` renders: `uv run pytest` stays green and a manual `GET /api/docs` on a tenant host returns 200 (Swagger; TEMPLATES/staticfiles/STATIC_URL are already configured from M0).

- [ ] **Step 8: Gate + commit**

```bash
git add easybiz/core/api config/urls.py tests/test_auth_api.py
git commit -m "Add JWT auth, login/me endpoints, and mounted tenant API"
```

---

### Task 6: Activate tenant-status and module-gate middleware

**Files:**
- Modify: `easybiz/core/kernel/middleware.py`
- Test: `tests/test_middleware.py`

**Interfaces:**
- Consumes: `request.tenant`, `state.is_enabled`, `registry` (installed module ids).
- Produces: `TenantStatusMiddleware` (403 `This tenant is suspended` when `request.tenant.is_active is False`); `ModuleGateMiddleware` (404 `Module '<id>' is not enabled for this tenant` for `/api/<installed-module>/…` when not enabled).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_middleware.py
from django.test import Client

from easybiz.core.kernel import tenants


def test_disabled_module_route_is_gated(synced, provision):
    provision(slug="acme")  # demo installed, not enabled
    resp = Client().get("/api/demo/widgets", HTTP_HOST="acme.localhost")
    assert resp.status_code == 404
    assert "not enabled" in resp.json()["detail"]


def test_non_module_path_not_gated(synced, provision):
    provision(slug="acme")
    # /api/auth/* is not a module segment -> reaches the endpoint (401, not the gate's 404)
    assert Client().get("/api/auth/me", HTTP_HOST="acme.localhost").status_code == 401


def test_suspended_tenant_is_forbidden(synced, provision):
    tenant = provision(slug="acme")
    tenants.suspend(tenant)
    resp = Client().get("/api/auth/me", HTTP_HOST="acme.localhost")
    assert resp.status_code == 403
    assert "suspended" in resp.json()["detail"]
```

- [ ] **Step 2: Run — expect fail** (stubs pass everything through: the gate test gets a Ninja 404 without the message; suspended gets 401).

- [ ] **Step 3: Implement `middleware.py`**

```python
"""Request gates: suspended-tenant block and per-tenant module routing."""
from __future__ import annotations

import re

from django.http import JsonResponse

_MODULE_PATH = re.compile(r"^/api/([a-z][a-z0-9_]*)/")


class TenantStatusMiddleware:
    """403 for every path when the resolved tenant is suspended."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        tenant = getattr(request, "tenant", None)
        if tenant is not None and tenant.is_active is False:
            return JsonResponse({"detail": "This tenant is suspended"}, status=403)
        return self.get_response(request)


class ModuleGateMiddleware:
    """404 for routes of an installed module the tenant has not enabled."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        match = _MODULE_PATH.match(request.path)
        if match:
            from easybiz.core.kernel import state
            from easybiz.core.kernel.registry import registry

            segment = match.group(1)
            tenant = getattr(request, "tenant", None)
            if (
                registry.manifest(segment) is not None
                and tenant is not None
                and not state.is_enabled(tenant, segment)
            ):
                return JsonResponse(
                    {"detail": f"Module '{segment}' is not enabled for this tenant"}, status=404
                )
        return self.get_response(request)
```

- [ ] **Step 4: Run — expect pass; full suite + gate.**

Note: middleware order (from M0 settings) is CORS → TenantMain → TenantStatus → ModuleGate → Common, so `request.tenant` is set before the gates run. Suspended check precedes the module gate.

- [ ] **Step 5: Commit**

```bash
git add easybiz/core/kernel/middleware.py tests/test_middleware.py
git commit -m "Activate tenant-status and module-gate middleware"
```

---

### Task 7: `iam/service` role management

**Files:**
- Modify: `easybiz/core/iam/service.py`
- Test: `tests/test_iam_roles.py`

**Interfaces:**
- Produces: `RoleError`; `assignable_permissions(tenant) -> set[str]` (core + enabled-module perms); `create_role(tenant, name, permissions, description="") -> Role` (rejects `*`, unknown/disabled perms, duplicate name); `role_permissions(role) -> list[str]`; `set_user_roles(user_id, role_names)` (raises `RoleError` on unknown role).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_iam_roles.py
import pytest
from django_tenants.utils import tenant_context

from easybiz.core.iam import service as iam
from easybiz.core.iam.service import RoleError
from easybiz.core.kernel import lifecycle


def test_create_role_and_guards(synced, db_tenant):
    lifecycle.enable_module(db_tenant, "demo")
    with tenant_context(db_tenant):
        role = iam.create_role(db_tenant, "viewer", ["demo.widget.read", "core.module.read"])
        assert set(iam.role_permissions(role)) == {"demo.widget.read", "core.module.read"}
        with pytest.raises(RoleError):
            iam.create_role(db_tenant, "star", ["*"])
        with pytest.raises(RoleError):
            iam.create_role(db_tenant, "bad", ["nope.perm"])
        with pytest.raises(RoleError):
            iam.create_role(db_tenant, "viewer", ["core.module.read"])  # duplicate


def test_assignable_excludes_disabled_module_perms(synced, db_tenant):
    with tenant_context(db_tenant):
        assert "core.module.read" in iam.assignable_permissions(db_tenant)
        assert "demo.widget.read" not in iam.assignable_permissions(db_tenant)  # demo not enabled
```

- [ ] **Step 2: Run — expect fail.**

- [ ] **Step 3: Implement (append to `iam/service.py`)**

```python
from django.db.models import Q

from easybiz.core.catalog.models import Permission
from easybiz.core.iam.models import Role, RolePermission, UserRole


class RoleError(Exception):
    """Invalid role definition or assignment (maps to HTTP 422)."""


def assignable_permissions(tenant) -> set[str]:
    enabled = state.enabled_module_ids(tenant)
    return set(
        Permission.objects.filter(Q(module__isnull=True) | Q(module_id__in=enabled))
        .values_list("code", flat=True)
    )


def role_permissions(role) -> list[str]:
    return sorted(role.permissions.values_list("permission", flat=True))


def create_role(tenant, name: str, permissions, description: str = "") -> Role:
    perms = list(permissions)
    if "*" in perms:
        raise RoleError("'*' is reserved for the system owner role")
    unknown = set(perms) - assignable_permissions(tenant)
    if unknown:
        raise RoleError(f"unknown or disabled permissions: {sorted(unknown)}")
    if Role.objects.filter(name=name).exists():
        raise RoleError(f"role {name!r} already exists")
    role = Role.objects.create(name=name, description=description, is_system=False)
    RolePermission.objects.bulk_create([RolePermission(role=role, permission=p) for p in perms])
    return role


def set_user_roles(user_id, role_names) -> None:
    roles = list(Role.objects.filter(name__in=list(role_names)))
    missing = set(role_names) - {r.name for r in roles}
    if missing:
        raise RoleError(f"unknown roles: {sorted(missing)}")
    UserRole.objects.filter(user_id=user_id).delete()
    UserRole.objects.bulk_create([UserRole(user_id=user_id, role=r) for r in roles])
```

(Keep `permissions_for`/`has_permission`/`menu_for` from Task 4; `state`/`registry` already imported.)

- [ ] **Step 4: Run — expect pass; gate; commit.**

```bash
git add easybiz/core/iam/service.py tests/test_iam_roles.py
git commit -m "Add role management to the iam service"
```

---

### Task 8: `users/service.create_user`

**Files:**
- Modify: `easybiz/core/users/service.py`
- Test: `tests/test_users_create.py`

**Interfaces:**
- Produces: `WeakPassword`; `create_user(email, tenant, password=None, name="") -> User` — reuses an existing user (no password needed); for a new email requires a ≥10-char password; ensures an active `Membership`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_users_create.py
import pytest

from easybiz.core.users import service as users
from easybiz.core.users.models import Membership, User
from easybiz.core.users.service import WeakPassword


def test_create_new_user_requires_password(synced, provision, request):
    tenant = provision(slug="acme")
    request.addfinalizer(lambda: User.objects.filter(email="new@acme.test").delete())
    with pytest.raises(WeakPassword):
        users.create_user("new@acme.test", tenant)  # new account, no password
    with pytest.raises(WeakPassword):
        users.create_user("new@acme.test", tenant, password="short")
    user = users.create_user("new@acme.test", tenant, password="change-me-now")
    assert Membership.objects.filter(user=user, tenant=tenant, is_active=True).exists()


def test_existing_user_reused_without_password(synced, provision):
    tenant = provision(slug="acme")
    other = provision(slug="zenith")
    owner = User.objects.get(email="owner@acme.test")
    reused = users.create_user("owner@acme.test", other)  # no password, existing account
    assert reused == owner
    assert Membership.objects.filter(user=owner, tenant=other).exists()
```

- [ ] **Step 2: Run — expect fail.**

- [ ] **Step 3: Implement (append to `users/service.py`)**

```python
from easybiz.core.users.models import Membership, User


class WeakPassword(Exception):
    """A new account was requested without a valid (≥10-char) password (HTTP 422)."""


def create_user(email, tenant, password=None, name: str = "") -> User:
    user = User.objects.filter(email=email.lower()).first()
    if user is None:
        if not password or len(password) < 10:
            raise WeakPassword("a new account needs a password of at least 10 characters")
        user = User.objects.create_user(email=email, password=password, name=name)
    Membership.objects.get_or_create(user=user, tenant=tenant, defaults={"is_active": True})
    return user
```

- [ ] **Step 4: Run — expect pass; gate; commit.**

```bash
git add easybiz/core/users/service.py tests/test_users_create.py
git commit -m "Add user creation service with password rule"
```

---

### Task 9: `/core/modules` endpoints

**Files:**
- Create: `easybiz/core/api/core_routes.py`; extend `easybiz/core/api/types.py`
- Modify: `easybiz/core/api/__init__.py` (mount `core_router`)
- Test: `tests/test_core_modules_api.py`

**Interfaces:**
- Produces: `GET /core/modules`, `POST /core/modules/{id}/enable`, `POST /core/modules/{id}/disable`, `DELETE /core/modules/{id}/data?confirm=true`. A `_module_view(tenant, id)` building `{id,name,version,status,requires[],optional[],blocked_by[]}` where `status ∈ {enabled,disabled,available}`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_core_modules_api.py
from django.test import Client


def _token(provision, slug="acme"):
    provision(slug=slug)
    r = Client().post(
        "/api/auth/login", data={"email": f"owner@{slug}.test", "password": "change-me-now"},
        content_type="application/json", HTTP_HOST=f"{slug}.localhost",
    )
    return r.json()["access_token"]


def _get(path, token, slug="acme"):
    return Client().get(path, HTTP_HOST=f"{slug}.localhost", HTTP_AUTHORIZATION=f"Bearer {token}")


def _post(path, token, slug="acme"):
    return Client().post(path, HTTP_HOST=f"{slug}.localhost", HTTP_AUTHORIZATION=f"Bearer {token}")


def test_list_and_enable_disable_module(synced, provision):
    token = _token(provision)  # owner has '*'
    listing = _get("/api/core/modules", token).json()
    demo = next(m for m in listing if m["id"] == "demo")
    assert demo["status"] == "available"

    assert _post("/api/core/modules/demo/enable", token).json()["status"] == "enabled"
    assert _post("/api/core/modules/demo/disable", token).json()["status"] == "disabled"
    assert _post("/api/core/modules/demo/enable", token).status_code == 200


def test_enable_twice_409(synced, provision):
    token = _token(provision)
    _post("/api/core/modules/demo/enable", token)
    assert _post("/api/core/modules/demo/enable", token).status_code == 409


def test_remove_data_needs_confirm_and_disabled(synced, provision):
    token = _token(provision)
    _post("/api/core/modules/demo/enable", token)
    assert Client().delete(
        "/api/core/modules/demo/data", HTTP_HOST="acme.localhost",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    ).status_code == 400  # no confirm
    _post("/api/core/modules/demo/disable", token)
    assert Client().delete(
        "/api/core/modules/demo/data?confirm=true", HTTP_HOST="acme.localhost",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    ).status_code == 200
```

- [ ] **Step 2: Run — expect fail.**

- [ ] **Step 3: Extend `api/types.py`**

```python
class ModuleOut(Schema):
    id: str
    name: str
    version: str
    status: str
    requires: list[str]
    optional: list[str]
    blocked_by: list[str]
```

- [ ] **Step 4: Write `api/core_routes.py` (modules section)**

```python
"""Tenant /core resource endpoints."""
from __future__ import annotations

from ninja import Router
from ninja.errors import HttpError

from easybiz.core.api.auth import perm
from easybiz.core.api.types import ModuleOut
from easybiz.core.kernel import lifecycle, state
from easybiz.core.kernel.registry import registry

router = Router()


def _module_view(tenant, module_id: str) -> ModuleOut:
    manifest = registry.manifest(module_id)
    enabled = state.enabled_module_ids(tenant)
    from easybiz.core.catalog.models import TenantModule

    row = TenantModule.objects.filter(tenant=tenant, module_id=module_id).first()
    if module_id in enabled:
        status = "enabled"
    elif row is not None:
        status = "disabled"
    else:
        status = "available"
    requires = [dep for dep, _ in manifest.requires] if manifest else []
    optional = [dep for dep, _ in manifest.optional] if manifest else []
    if status == "enabled":
        blocked_by = [d for d in registry.dependents_of(module_id) if d in enabled]
    else:
        blocked_by = [d for d in requires if d not in enabled]
    return ModuleOut(
        id=module_id, name=manifest.name if manifest else module_id,
        version=manifest.version if manifest else "", status=status,
        requires=requires, optional=optional, blocked_by=blocked_by,
    )


@router.get("/modules", auth=perm("core.module.read"), response=list[ModuleOut])
def list_modules(request):
    """Every installed module with its per-tenant status and dependency blockers."""
    return [_module_view(request.tenant, mid) for mid in sorted(registry.module_ids())]


@router.post("/modules/{module_id}/enable", auth=perm("core.module.manage"), response=ModuleOut)
def enable(request, module_id: str):
    try:
        lifecycle.enable_module(request.tenant, module_id, actor_id=request.auth.id)
    except lifecycle.LifecycleError as exc:
        raise HttpError(409, str(exc)) from exc
    return _module_view(request.tenant, module_id)


@router.post("/modules/{module_id}/disable", auth=perm("core.module.manage"), response=ModuleOut)
def disable(request, module_id: str):
    try:
        lifecycle.disable_module(request.tenant, module_id, actor_id=request.auth.id)
    except lifecycle.LifecycleError as exc:
        raise HttpError(409, str(exc)) from exc
    return _module_view(request.tenant, module_id)


@router.delete("/modules/{module_id}/data", auth=perm("core.module.manage"), response=ModuleOut)
def remove_data(request, module_id: str, confirm: bool = False):
    if not confirm:
        raise HttpError(400, "pass ?confirm=true to remove module data")
    try:
        lifecycle.remove_module_data(request.tenant, module_id, actor_id=request.auth.id)
    except lifecycle.LifecycleError as exc:
        raise HttpError(409, str(exc)) from exc
    return _module_view(request.tenant, module_id)
```

(Route order note P8: fixed paths are fine here since all module routes are parameterized consistently; no `/modules/sync` collision in the tenant API.)

- [ ] **Step 5: Mount `core_router` in `api/__init__.py`**

```python
from easybiz.core.api.core_routes import router as core_router

api.add_router("/core", core_router)
```

- [ ] **Step 6: Run — expect pass; full suite + gate; commit.**

```bash
git add easybiz/core/api tests/test_core_modules_api.py
git commit -m "Add /core/modules endpoints"
```

---

### Task 10: `/core/roles` endpoints

**Files:**
- Modify: `easybiz/core/api/core_routes.py`, `easybiz/core/api/types.py`
- Test: `tests/test_core_roles_api.py`

**Interfaces:**
- Produces: `GET /core/roles` (`core.role.read`), `POST /core/roles` (`core.role.manage`) → 201; maps `RoleError` → 422.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_core_roles_api.py
from django.test import Client

from tests.test_core_modules_api import _token


def test_create_and_list_role(synced, provision):
    token = _token(provision)
    c = Client()
    resp = c.post(
        "/api/core/roles",
        data={"name": "reader", "permissions": ["core.module.read"]},
        content_type="application/json", HTTP_HOST="acme.localhost",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    assert resp.status_code == 201
    names = [r["name"] for r in c.get(
        "/api/core/roles", HTTP_HOST="acme.localhost", HTTP_AUTHORIZATION=f"Bearer {token}"
    ).json()]
    assert "reader" in names and "owner" in names


def test_create_role_star_rejected(synced, provision):
    token = _token(provision)
    resp = Client().post(
        "/api/core/roles", data={"name": "x", "permissions": ["*"]},
        content_type="application/json", HTTP_HOST="acme.localhost",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    assert resp.status_code == 422
```

- [ ] **Step 2: Run — expect fail.**

- [ ] **Step 3: Extend `types.py` + add role endpoints**

```python
# types.py
class RoleIn(Schema):
    name: str
    description: str = ""
    permissions: list[str]


class RoleOut(Schema):
    id: str
    name: str
    description: str
    is_system: bool
    permissions: list[str]
```

```python
# core_routes.py
from easybiz.core.api.types import RoleIn, RoleOut
from easybiz.core.iam import service as iam
from easybiz.core.iam.models import Role
from easybiz.core.audit import service as audit


def _role_view(role) -> RoleOut:
    return RoleOut(
        id=str(role.id), name=role.name, description=role.description,
        is_system=role.is_system, permissions=iam.role_permissions(role),
    )


@router.get("/roles", auth=perm("core.role.read"), response=list[RoleOut])
def list_roles(request):
    return [_role_view(r) for r in Role.objects.order_by("name")]


@router.post("/roles", auth=perm("core.role.manage"), response={201: RoleOut})
def create_role(request, data: RoleIn):
    try:
        role = iam.create_role(request.tenant, data.name, data.permissions, data.description)
    except iam.RoleError as exc:
        raise HttpError(422, str(exc)) from exc
    audit.record(request.auth.id, "role.created", entity="role", entity_id=str(role.id))
    return 201, _role_view(role)
```

- [ ] **Step 4: Run — expect pass; gate; commit.**

```bash
git add easybiz/core/api tests/test_core_roles_api.py
git commit -m "Add /core/roles endpoints"
```

---

### Task 11: `/core/users` endpoints

**Files:**
- Modify: `easybiz/core/api/core_routes.py`, `easybiz/core/api/types.py`
- Test: `tests/test_core_users_api.py`

**Interfaces:**
- Produces: `GET /core/users` (`core.user.read`), `POST /core/users` (`core.user.manage`) → 201, `DELETE /core/users/{id}` (`core.user.manage`) → 204 (publishes `core.membership.removed`, 409 on self). Maps `WeakPassword`/`RoleError` → 422.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_core_users_api.py
from django.test import Client

from tests.test_core_modules_api import _token


def test_create_user_and_list(synced, provision, request):
    from easybiz.core.users.models import User

    request.addfinalizer(lambda: User.objects.filter(email="new@acme.test").delete())
    token = _token(provision)
    resp = Client().post(
        "/api/core/users",
        data={"email": "new@acme.test", "password": "change-me-now", "roles": ["owner"]},
        content_type="application/json", HTTP_HOST="acme.localhost",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    assert resp.status_code == 201
    emails = [u["email"] for u in Client().get(
        "/api/core/users", HTTP_HOST="acme.localhost", HTTP_AUTHORIZATION=f"Bearer {token}"
    ).json()]
    assert "new@acme.test" in emails


def test_new_user_without_password_422(synced, provision):
    token = _token(provision)
    resp = Client().post(
        "/api/core/users", data={"email": "np@acme.test", "roles": []},
        content_type="application/json", HTTP_HOST="acme.localhost",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    assert resp.status_code == 422


def test_cannot_delete_self(synced, provision):
    from easybiz.core.users.models import User

    token = _token(provision)
    owner = User.objects.get(email="owner@acme.test")
    resp = Client().delete(
        f"/api/core/users/{owner.id}", HTTP_HOST="acme.localhost",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    assert resp.status_code == 409
```

- [ ] **Step 2: Run — expect fail.**

- [ ] **Step 3: Extend `types.py` + add user endpoints**

```python
# types.py
class UserIn(Schema):
    email: str
    password: str | None = None
    name: str = ""
    roles: list[str] = []


class UserOut(Schema):
    id: str
    email: str
    roles: list[str]
```

```python
# core_routes.py
from easybiz.core.api.types import UserIn, UserOut
from easybiz.core.events.models import OutboxEvent
from easybiz.core.iam.models import UserRole
from easybiz.core.users import service as users
from easybiz.core.users.models import Membership, User


def _user_view(tenant, user) -> UserOut:
    role_names = list(
        UserRole.objects.filter(user_id=user.id).values_list("role__name", flat=True)
    )
    return UserOut(id=str(user.id), email=user.email, roles=sorted(role_names))


@router.get("/users", auth=perm("core.user.read"), response=list[UserOut])
def list_users(request):
    members = Membership.objects.filter(tenant=request.tenant, is_active=True).select_related("user")
    return [_user_view(request.tenant, m.user) for m in members]


@router.post("/users", auth=perm("core.user.manage"), response={201: UserOut})
def create_user(request, data: UserIn):
    try:
        user = users.create_user(data.email, request.tenant, password=data.password, name=data.name)
        iam.set_user_roles(user.id, data.roles)
    except (users.WeakPassword, iam.RoleError) as exc:
        raise HttpError(422, str(exc)) from exc
    audit.record(request.auth.id, "user.added", entity="user", entity_id=str(user.id))
    return 201, _user_view(request.tenant, user)


@router.delete("/users/{user_id}", auth=perm("core.user.manage"), response={204: None})
def delete_user(request, user_id: str):
    if str(request.auth.id) == user_id:
        raise HttpError(409, "you cannot remove yourself")
    membership = Membership.objects.filter(tenant=request.tenant, user_id=user_id).first()
    if membership is None:
        raise HttpError(404, "user is not a member of this tenant")
    UserRole.objects.filter(user_id=user_id).delete()
    membership.delete()
    OutboxEvent.objects.create(
        name="core.membership.removed", producer="core", payload={"user_id": user_id}
    )
    audit.record(request.auth.id, "user.removed", entity="user", entity_id=user_id)
    return 204, None
```

(`OutboxEvent.objects.create` directly is the M5 shim; `events.service.publish` replaces it in M5.)

- [ ] **Step 4: Run — expect pass; gate; commit.**

```bash
git add easybiz/core/api tests/test_core_users_api.py
git commit -m "Add /core/users endpoints"
```

---

### Task 12: `/core/audit` endpoint

**Files:**
- Modify: `easybiz/core/api/core_routes.py`, `easybiz/core/api/types.py`
- Test: `tests/test_core_audit_api.py`

**Interfaces:**
- Produces: `GET /core/audit?limit=` (`core.audit.read`) → `[{at, actor_id, action, entity, entity_id}]`, newest first, `limit` max 200.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_core_audit_api.py
from django.test import Client

from tests.test_core_modules_api import _token


def test_audit_lists_actions(synced, provision):
    token = _token(provision)
    Client().post("/api/core/modules/demo/enable", HTTP_HOST="acme.localhost",
                  HTTP_AUTHORIZATION=f"Bearer {token}")
    rows = Client().get("/api/core/audit", HTTP_HOST="acme.localhost",
                        HTTP_AUTHORIZATION=f"Bearer {token}").json()
    actions = {r["action"] for r in rows}
    assert {"tenant.provisioned", "module.enabled"} <= actions
```

- [ ] **Step 2: Run — expect fail.**

- [ ] **Step 3: Add the endpoint + `AuditOut`**

```python
# types.py
class AuditOut(Schema):
    at: str
    actor_id: str | None
    action: str
    entity: str
    entity_id: str
```

```python
# core_routes.py
from easybiz.core.api.types import AuditOut
from easybiz.core.audit.models import AuditLog


@router.get("/audit", auth=perm("core.audit.read"), response=list[AuditOut])
def list_audit(request, limit: int = 50):
    limit = min(limit, 200)
    rows = AuditLog.objects.order_by("-at")[:limit]
    return [
        AuditOut(
            at=r.at.isoformat(), actor_id=str(r.actor_id) if r.actor_id else None,
            action=r.action, entity=r.entity, entity_id=r.entity_id,
        )
        for r in rows
    ]
```

- [ ] **Step 4: Run — expect pass; full suite + gate; commit.**

```bash
git add easybiz/core/api tests/test_core_audit_api.py
git commit -m "Add /core/audit endpoint"
```

---

### Task 13: README + milestone close

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update README** — Status: **M4 complete** (authentication, authorization, audit, and the tenant API). JWT `/api/auth/login` + `/auth/me`; the `perm()` guard; suspended-tenant (403) + module-gate (404) middleware; Swagger at `/api/docs`; and the `/api/core/*` endpoints — modules (list/enable/disable/remove-data), roles (list/create), users (list/create/delete), audit. Document the auth flow and add `/api/docs` to the command notes. Next: **M5** (events dispatcher) and **M6** (the real Timesheets module). Multiple auth methods (2FA, magic link, social/SSO, refresh tokens) remain deferred to **F13**.

- [ ] **Step 2: Full gate**

Run: `uv run pytest && uv run ruff check . && uv run ruff format --check . && uv run mypy easybiz config && uv run manage.py makemigrations --check --dry-run`
Expected: all green; `No changes detected` (M4a adds no models).

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "Document M4a auth engine and tenant API in README"
```

---

## M4 Definition of Done

- [ ] `sync_catalog` upserts the 7 core permissions (`module=null`).
- [ ] `POST /api/auth/login` returns a token for valid creds + active membership; wrong password / unknown email / no membership all return the same 401 `Invalid credentials`.
- [ ] `GET /api/auth/me` returns id/email/permissions/enabled_modules/menu; requires a valid tenant token.
- [ ] A token for tenant A is refused by tenant B (I9); the tenant API is not served on the public host (`/api/*` → 404 there).
- [ ] `has_permission` matches `*` / exact / `module.*`; `audit.record` writes in the tenant schema; lifecycle/provisioning route through it.
- [ ] Suspended tenant → 403 everywhere; a disabled module's route → 404 with the gate message; `/api/auth/*` and non-module paths are untouched.
- [ ] `/core/modules` lists status + `blocked_by`; enable/disable/remove-data work with 409/400 guards; `create_role` rejects `*`/unknown/duplicate (422); `POST /core/users` enforces the new-account password rule (422) and assigns roles; `DELETE /core/users/{id}` refuses self (409), publishes `core.membership.removed`, audits; `/core/audit` lists newest-first (limit ≤ 200). Every endpoint declares `auth=perm(...)` with the §7.1 permission.
- [ ] `/api/docs` renders (Swagger). `uv run pytest` green on real PostgreSQL; `ruff` + `mypy easybiz config` clean; README updated; commits short, no attribution.
```
