# F23a — Agent Tooling: Read-Only Tool Registry + HTTP Transport — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the transport-agnostic tool layer for agents — a registry of read tools wrapping existing `queries`, invocation that enforces the same `perm()` the HTTP endpoint uses + validates inputs + audits, lazy discovery, and a thin `/api/tools` HTTP transport — all dependency-free.

**Architecture:** `easybiz/core/tools/` holds a `Tool` (name, description, risk tier, `perm()` code, `idempotent`, input schema, handler) and a process-global `registry`. `service.invoke(name, inputs, user_id)` gates on existence → caller's effective iam permissions (the exact HTTP gate) → risk tier (read-only in this slice) → pydantic input validation → calls the handler (which calls the existing query/service) → audits. Core registers six read tools. The `/api/tools` router (tenant-JWT authed) exposes lazy discovery (`list`/`search` compact, `describe` with the input schema) filtered to tools the caller is authorized for, and `invoke`. The real MCP wire protocol, scoped agent keys, and write/admin tools defer to a later slice with F13.

**Tech Stack:** Python 3.13, Django 6.1, django-ninja/pydantic, `uv`/pytest. No new dependencies.

**Spec:** `ERP-CORE-SPEC.md` §F23 (slice a — read-only tool layer). Later slices: (b) agent keys + write tools [F13], (c) chatbot, (d) per-module tool contributions [F17 contract kit], (e) composite tools + response shaping [F21].

## Global Constraints

- One tool layer, many transports: a tool **wraps an existing `queries`/service function** — no business logic is re-implemented.
- Every invocation enforces the tool's `perm()` against the caller's effective iam permissions — the **same gate** the HTTP endpoint uses; nothing bypasses iam.
- Inputs are pydantic-validated structured data (reuse `…Params`/`Schema`); no free-form code/SQL. Every invocation is audited.
- Risk tier is mechanical from command-vs-query: this slice registers and invokes **read** tools only; `write`/`admin` tools are refused (they need an agent write scope — F13).
- Tenant isolation is structural: a tool runs inside the caller's request/tenant schema, so a query only sees that tenant's data.
- Imports at top; domain errors subclass `DomainError` (mapped by the one `@api.exception_handler`).

## Review Focus

- **Permission bypass** — invoking a tool whose `perm()` the caller lacks must be denied (403), identical to the HTTP gate; a `perm=None` tool (e.g. context) is allowed to any authenticated caller. (Task 2.)
- **Write/admin exposure** — a non-`read` tool must be refused in this slice (403), never invoked. (Task 2.)
- **Input injection** — malformed/extra inputs must be pydantic-rejected (422) before the handler runs; raw input never reaches the query unvalidated. (Task 2.)
- **Discovery leak** — `list`/`search`/`describe` must only surface tools the caller is authorized for (no advertising unauthorized tools). (Tasks 3 & 4.)
- **Unknown tool** — invoking/describing an unknown name is a clean 404, not a crash. (Task 2/4.)

---

### Task 1: Tool registry + tier enum

**Files:**
- Create: `easybiz/core/tools/__init__.py`
- Create: `easybiz/core/tools/enums.py`
- Create: `easybiz/core/tools/registry.py`
- Modify: `tests/conftest.py` (autouse `_reset_tools` fixture, mirroring `_reset_capabilities`)
- Test: `tests/test_tool_registry.py`

**Interfaces:**
- Produces:
  - `enums.ToolTier(StrEnum)` — `READ="read"`, `WRITE="write"`, `ADMIN="admin"`, with `choices()`.
  - `registry.Tool` (frozen dataclass): `name: str`, `description: str`, `tier: ToolTier`, `perm: str | None`, `idempotent: bool`, `input_schema: type | None`, `handler` (callable `(user_id, params) -> object`).
  - `registry.ToolRegistry` — `register(tool)` (raise on duplicate name), `get(name) -> Tool | None`, `all() -> list[Tool]`, `search(query) -> list[Tool]` (case-insensitive substring over name + description; empty query → all).
  - module-global `registry = ToolRegistry()`.
- conftest `_reset_tools` snapshots/restores `registry._tools` around each test (process-global isolation).

- [ ] **Step 1: Write the failing tests**

```python
from easybiz.core.tools.enums import ToolTier
from easybiz.core.tools.registry import Tool, ToolRegistry

def _tool(name, desc="d"):
    return Tool(name=name, description=desc, tier=ToolTier.READ, perm=None,
                idempotent=True, input_schema=None, handler=lambda uid, p: name)

def test_register_get_search():
    r = ToolRegistry()
    r.register(_tool("core.modules.list", "list modules"))
    r.register(_tool("core.roles.list", "list roles"))
    assert r.get("core.modules.list").description == "list modules"
    assert {t.name for t in r.search("roles")} == {"core.roles.list"}
    assert {t.name for t in r.search("")} == {"core.modules.list", "core.roles.list"}

def test_duplicate_rejected():
    import pytest
    r = ToolRegistry()
    r.register(_tool("x"))
    with pytest.raises(ValueError):
        r.register(_tool("x"))
```

- [ ] **Step 2: Run them, verify they fail** — Run: `uv run pytest tests/test_tool_registry.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement** the enum, `Tool`, `ToolRegistry`, and the conftest fixture.
- [ ] **Step 4: Run them, verify they pass** — Expected: PASS.
- [ ] **Step 5: Commit** — `git add easybiz/core/tools tests/conftest.py tests/test_tool_registry.py && git commit -m "Add agent tool registry and risk-tier enum"`

---

### Task 2: Invocation service (perm gate, validation, audit)

**Files:**
- Create: `easybiz/core/tools/service.py`
- Test: `tests/test_tool_invoke.py`

**Interfaces:**
- Consumes: `registry`, `iam.has_permission`, `iam_cache.cached_permissions_for`, `audit.record`, `ToolTier`.
- Produces:
  - `class ToolError(DomainError)` — carries a status (404/403/422).
  - `invoke(name, raw_inputs: dict, *, user_id) -> object` — order: `registry.get` or `ToolError(404)`; `_allowed(tool, perms)` or `ToolError(403, "missing permission")`; `tool.tier != READ` → `ToolError(403, "only read tools are available (write/admin need an agent key)")`; validate `tool.input_schema(**raw_inputs)` (on pydantic `ValidationError` → `ToolError(422)`); `result = tool.handler(user_id, params)`; `audit.record(user_id, "tool.invoked", entity="tool", entity_id=name)`; return result.
  - `accessible(user_id) -> list[Tool]` — `registry.all()` filtered by `_allowed(tool, cached_permissions_for(user_id))`.
  - `describe(tool) -> dict` — `{name, description, tier, perm, input_schema}` where `input_schema` is `tool.input_schema.model_json_schema()` or `None`.
  - `_allowed(tool, perms) -> bool` — `tool.perm is None or iam.has_permission(perms, tool.perm)`.

- [ ] **Step 1: Write the failing tests** (register throwaway tools into the global registry; `_reset_tools` restores)

```python
import pytest
from django_tenants.utils import tenant_context
from ninja import Schema
from easybiz.core.tools import registry as reg, service
from easybiz.core.tools.enums import ToolTier
from easybiz.core.tools.registry import Tool
from easybiz.core.iam.models import Role, RolePermission, UserRole

class _LimitIn(Schema):
    limit: int = 10

def _reader(perms):
    role = Role.objects.create(name="r")
    RolePermission.objects.bulk_create([RolePermission(role=role, permission=p) for p in perms])
    uid = "22222222-2222-2222-2222-222222222222"
    UserRole.objects.create(user_id=uid, role=role)
    return uid

def _register(**kw):
    base = dict(name="t.read", description="d", tier=ToolTier.READ, perm="core.audit.read",
                idempotent=True, input_schema=None, handler=lambda uid, p: {"ok": True})
    reg.registry.register(Tool(**{**base, **kw}))

def test_unknown_tool_404(synced, db_tenant):
    with tenant_context(db_tenant):
        with pytest.raises(service.ToolError) as e:
            service.invoke("nope", {}, user_id="00000000-0000-0000-0000-000000000000")
        assert e.value.status == 404

def test_missing_permission_403(synced, db_tenant):
    with tenant_context(db_tenant):
        _register()
        uid = _reader(["core.user.read"])  # lacks core.audit.read
        with pytest.raises(service.ToolError) as e:
            service.invoke("t.read", {}, user_id=uid)
        assert e.value.status == 403

def test_write_tool_refused(synced, db_tenant):
    with tenant_context(db_tenant):
        _register(name="t.write", tier=ToolTier.WRITE, perm=None)
        uid = _reader([])
        with pytest.raises(service.ToolError) as e:
            service.invoke("t.write", {}, user_id=uid)
        assert e.value.status == 403

def test_invalid_input_422(synced, db_tenant):
    with tenant_context(db_tenant):
        _register(name="t.in", perm=None, input_schema=_LimitIn)
        uid = _reader([])
        with pytest.raises(service.ToolError) as e:
            service.invoke("t.in", {"limit": "not-an-int"}, user_id=uid)
        assert e.value.status == 422

def test_happy_path_invokes_and_audits(synced, db_tenant):
    from easybiz.core.audit.models import AuditLog
    with tenant_context(db_tenant):
        _register()
        uid = _reader(["core.audit.read"])
        assert service.invoke("t.read", {}, user_id=uid) == {"ok": True}
        assert AuditLog.objects.filter(action="tool.invoked", entity_id="t.read").exists()

def test_accessible_filters_by_permission(synced, db_tenant):
    with tenant_context(db_tenant):
        _register()  # perm core.audit.read
        _register(name="t.open", perm=None)
        uid = _reader([])  # no perms
        names = {t.name for t in service.accessible(uid)}
        assert "t.open" in names and "t.read" not in names
```

- [ ] **Step 2: Run them, verify they fail** — Run: `uv run pytest tests/test_tool_invoke.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement** `service.py`.
- [ ] **Step 4: Run them, verify they pass** — Expected: PASS.
- [ ] **Step 5: Commit** — `git add easybiz/core/tools/service.py tests/test_tool_invoke.py && git commit -m "Add tool invocation (perm gate, tier guard, input validation, audit)"`

---

### Task 3: Core read tools

**Files:**
- Create: `easybiz/core/tools/core_tools.py`
- Modify: `easybiz/core/api/__init__.py` (import `core_tools` so the tools register at app load)
- Test: `tests/test_core_tools.py`

**Interfaces:**
- Produces: `core_tools.register_core_tools()` (idempotent-ish; called at import) registering six read tools, each `tier=READ`, `idempotent=True`, wrapping an existing query/service:
  - `core.context` — `perm=None` — `{tenant: {slug, name}, enabled_modules: [...]}` (via `state.enabled_module_ids`).
  - `core.modules.list` — `core.module.read` — installed modules with per-tenant status (reuse the `_module_view` shaping).
  - `core.roles.list` — `core.role.read` — `iam.list_roles()` shaped.
  - `core.permissions.list` — `core.role.read` — `iam.permission_groups(tenant)`.
  - `core.users.list` — `core.user.read` — active members shaped `{id, email, roles}`.
  - `core.audit.list` — `core.audit.read` — input `AuditQuery(limit: int = 50)` (cap 200) — audit rows.
- Handlers read the tenant from `connection.tenant` (set by the request/`tenant_context`), so no tenant arg is threaded.

- [ ] **Step 1: Write the failing tests**

```python
from django_tenants.utils import tenant_context
from easybiz.core.tools import service
from easybiz.core.tools.enums import ToolTier
from easybiz.core.tools.registry import registry

def test_core_tools_registered():
    names = {t.name for t in registry.all()}
    assert {"core.context", "core.modules.list", "core.roles.list",
            "core.permissions.list", "core.users.list", "core.audit.list"} <= names
    assert registry.get("core.audit.list").perm == "core.audit.read"
    assert all(t.tier == ToolTier.READ for t in registry.all())

def test_context_tool_runs_for_any_user(synced, db_tenant):
    from easybiz.core.iam.models import Role, UserRole
    with tenant_context(db_tenant):
        role = Role.objects.create(name="r")
        uid = "33333333-3333-3333-3333-333333333333"
        UserRole.objects.create(user_id=uid, role=role)
        out = service.invoke("core.context", {}, user_id=uid)
        assert "enabled_modules" in out

def test_audit_tool_requires_permission(synced, db_tenant):
    import pytest
    from easybiz.core.iam.models import Role, RolePermission, UserRole
    with tenant_context(db_tenant):
        role = Role.objects.create(name="r")
        RolePermission.objects.create(role=role, permission="core.audit.read")
        uid = "44444444-4444-4444-4444-444444444444"
        UserRole.objects.create(user_id=uid, role=role)
        out = service.invoke("core.audit.list", {"limit": 5}, user_id=uid)
        assert isinstance(out, list)
```

- [ ] **Step 2: Run them, verify they fail** — Run: `uv run pytest tests/test_core_tools.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement** `core_tools.py` (register at import) and import it from `easybiz/core/api/__init__.py`.
- [ ] **Step 4: Run them, verify they pass** — Expected: PASS.
- [ ] **Step 5: Commit** — `git add easybiz/core/tools/core_tools.py easybiz/core/api/__init__.py tests/test_core_tools.py && git commit -m "Register core read tools (context, modules, roles, permissions, users, audit)"`

---

### Task 4: HTTP tools transport

**Files:**
- Create: `easybiz/core/api/tools_routes.py`
- Modify: `easybiz/core/api/__init__.py` (mount the router at `/tools`)
- Modify: `easybiz/core/api/types.py` (add `ToolSummaryOut`, `ToolDetailOut`)
- Test: `tests/test_tools_api.py`

**Interfaces:**
- Consumes: `tools.service` (`accessible`, `describe`, `invoke`, `ToolError`), the `authenticated` guard.
- Produces endpoints under `/api/tools` (all `auth=authenticated`):
  - `GET /tools?q=` → `list[ToolSummaryOut]` (`{name, description, tier}`) — `service.accessible(request.auth.id)` optionally `search`-filtered; perm-filtered so unauthorized tools never appear.
  - `GET /tools/{name}` → `ToolDetailOut` (`{name, description, tier, perm, input_schema}`) — 404 if unknown; 403 if the caller is not authorized for it.
  - `POST /tools/{name}/invoke` → the tool result (JSON) — `service.invoke(name, body, user_id=request.auth.id)`; `ToolError` maps to its status via the central handler.
- `ToolSummaryOut`/`ToolDetailOut` are ninja `Schema`s in `api/types.py`.

- [ ] **Step 1: Write the failing tests** (reuse the `provision` + login helpers pattern)

```python
# _owner(provision, slug) logs in the tenant owner (holds *); _limited_token for a scoped user.
def test_list_filtered_by_permission(synced, provision):
    token = _owner(provision, "t1")
    names = {t["name"] for t in _req("get", "/api/tools", token, "t1").json()}
    assert "core.context" in names and "core.audit.list" in names  # owner holds *

def test_describe_unknown_404(synced, provision):
    token = _owner(provision, "t2")
    assert _req("get", "/api/tools/nope", token, "t2").status_code == 404

def test_invoke_happy(synced, provision):
    token = _owner(provision, "t3")
    r = _req("post", "/api/tools/core.context/invoke", token, "t3", {})
    assert r.status_code == 200 and "enabled_modules" in r.json()

def test_invoke_denied_for_unscoped_user(synced, provision):
    from easybiz.core.tenancy.models import Tenant
    _owner(provision, "t4")
    tenant = Tenant.objects.get(slug="t4")
    tok = _limited_token(tenant, ["core.user.read"])  # lacks core.audit.read
    assert _req("post", "/api/tools/core.audit.list/invoke", tok, "t4", {}).status_code == 403
    assert "core.audit.list" not in {t["name"] for t in _req("get", "/api/tools", tok, "t4").json()}
```

- [ ] **Step 2: Run them, verify they fail** — Run: `uv run pytest tests/test_tools_api.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement** `tools_routes.py`, mount it, add the types.
- [ ] **Step 4: Run them, verify they pass** — Expected: PASS.
- [ ] **Step 5: Run the full suite** — Run: `uv run pytest -q` — Expected: all pass.
- [ ] **Step 6: Commit** — `git add -A && git commit -m "Add /api/tools transport (lazy discovery + invoke, perm-filtered)"`

---

## Post-implementation
- Update `README.md` Status with a short F23a paragraph (read-only tool registry + `/api/tools`; MCP wire protocol + agent keys + write tools deferred to a later slice with F13).
- **Security review before the PR** (standing instruction — this is the agent authorization surface): `/security-review` on the branch; fix High/Medium; then open the PR.
- Later F23 slices (noted, not built): (b) scoped agent keys + write tools [F13], (c) integrated chatbot, (d) per-module tool contributions + contract tests, (e) composite tools + response shaping [F21], and the MCP stdio/streamable-HTTP wire server.
