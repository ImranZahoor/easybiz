# F23d — Agent Tooling: Per-Module Tool Contributions — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let modules contribute their own tools to the registry, gated per tenant by module enablement, with the F17 contract kit verifying every module tool is well-formed — proven by Timesheets contributing read tools.

**Architecture:** A `Tool` gains an optional `module_id` (core tools keep `None`). `tools.service` gates discovery and invocation by module enablement for the current tenant (a module tool is invisible/404 when its module is disabled — the same gate the HTTP layer applies), on top of the existing perm gate. Modules register tools in `<pkg>/tools.py`, imported at startup alongside `handlers`/`providers`. The F17 contract kit gains `check_tools`: every module tool's name is prefixed with the module id, its `perm` is declared by the module (or core), and its tier is valid.

**Tech Stack:** Python 3.13, Django 6.1, django-ninja/pydantic, `uv`/pytest. No new dependencies.

**Spec:** `ERP-CORE-SPEC.md` §F23 slice (d) — per-module tool contributions + contract tests. Builds on F23a (registry/invocation/transport) and F17 (contract kit). Slices (b) agent keys + write tools, (c) chatbot, (e) composite/shaping, and the MCP wire server remain deferred.

## Global Constraints

- A module tool wraps the module's existing `queries` — no business logic re-implemented.
- Module-tool availability is gated per tenant by `state.is_enabled(tenant, module_id)` — the same enablement that gates the module's HTTP routes (I7); a disabled module's tools are neither listed nor invocable.
- Invocation still enforces the tool's `perm()` against the caller's effective iam permissions; the module gate is checked **before** the perm gate (a disabled module's tool is a clean 404, not a 403, mirroring the HTTP module gate — never leaking which tools a disabled module has).
- Read-only this slice (write/admin tools wait for agent keys, F13).
- Imports at top; `DomainError` mapping; no new deps.

## Review Focus

- **Disabled-module gating** — a module tool must not appear in `list`/`describe` and must 404 on `invoke` when its module is disabled for the caller's tenant, even for a caller who holds its permission. (Task 1.)
- **Enabled + permitted** — when the module is enabled and the caller holds the tool's perm, the tool lists and invokes and returns the module's data. (Task 2.)
- **Enabled but unpermitted** — an enabled-module tool the caller lacks the perm for is still denied (403) and not listed. (Task 1/2.)
- **Contract: undeclared tool permission** — a module tool whose `perm` the module does not declare (and isn't core) is flagged by `check_tools`. (Task 3.)
- **Contract: tool name prefix** — a module tool whose name isn't prefixed `<id>.` is flagged. (Task 3.)

---

### Task 1: Module-id on Tool + enablement gating

**Files:**
- Modify: `easybiz/core/tools/registry.py` (add `module_id`)
- Modify: `easybiz/core/tools/service.py` (gate by module enablement)
- Test: `tests/test_tool_module_gating.py`

**Interfaces:**
- `Tool` gains a trailing field `module_id: str | None = None` (core tools unaffected; module tools pass it by keyword).
- `service._enabled(tool) -> bool` — `tool.module_id is None or state.is_enabled(connection.tenant, tool.module_id)`.
- `accessible(user_id)` additionally filters by `_enabled(tool)`.
- `invoke(...)` checks, in order: existence → `_enabled` (else `ToolError(404, "tool not available")`) → perm (403) → tier (403) → input validation (422).

- [ ] **Step 1: Write the failing tests** (register a throwaway module tool for the `demo` module; `demo` is enableable via `db_tenant`)

```python
import pytest
from django_tenants.utils import tenant_context
from easybiz.core.kernel import lifecycle
from easybiz.core.iam.models import Role, RolePermission, UserRole
from easybiz.core.tools import registry as reg, service
from easybiz.core.tools.enums import ToolTier
from easybiz.core.tools.registry import Tool

def _tool():
    reg.registry.register(Tool(name="demo.thing.list", description="d", tier=ToolTier.READ,
        perm=None, idempotent=True, input_schema=None, handler=lambda u, p: ["ok"],
        module_id="demo"))

def _user(perms=()):
    role = Role.objects.create(name="r")
    RolePermission.objects.bulk_create([RolePermission(role=role, permission=p) for p in perms])
    uid = "22222222-2222-2222-2222-222222222222"; UserRole.objects.create(user_id=uid, role=role)
    return uid

def test_module_tool_404_when_disabled(synced, db_tenant):
    with tenant_context(db_tenant):
        _tool(); uid = _user()
        with pytest.raises(service.ToolError) as e:
            service.invoke("demo.thing.list", {}, user_id=uid)   # demo not enabled
        assert e.value.status == 404
        assert "demo.thing.list" not in {t.name for t in service.accessible(uid)}

def test_module_tool_available_when_enabled(synced, db_tenant):
    _tool()
    lifecycle.enable_module(db_tenant, "demo")
    with tenant_context(db_tenant):
        uid = _user()
        assert service.invoke("demo.thing.list", {}, user_id=uid) == ["ok"]
        assert "demo.thing.list" in {t.name for t in service.accessible(uid)}

def test_core_tool_unaffected(synced, db_tenant):
    with tenant_context(db_tenant):
        uid = _user()
        assert "core.context" in {t.name for t in service.accessible(uid)}  # module_id None
```

- [ ] **Step 2: Run them, verify they fail** — Run: `uv run pytest tests/test_tool_module_gating.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement** the `module_id` field and `_enabled` gating (import `state`, `connection`).
- [ ] **Step 4: Run them, verify they pass** — Expected: PASS.
- [ ] **Step 5: Commit** — `git add easybiz/core/tools/registry.py easybiz/core/tools/service.py tests/test_tool_module_gating.py && git commit -m "Gate module-contributed tools by per-tenant enablement"`

---

### Task 2: Timesheets tool contributions

**Files:**
- Create: `easybiz/modules/timesheets/tools.py`
- Modify: `easybiz/core/kernel/registry.py` (`import_module_code` also imports `<pkg>.tools`)
- Test: `tests/test_timesheets_tools.py`

**Interfaces:**
- Produces `timesheets/tools.py` registering (idempotently, at import) two read tools, `module_id="timesheets"`, `tier=READ`:
  - `timesheets.projects.list` — `perm="timesheets.project.read"` — `[p.model_dump() for p in queries.all_projects()]`.
  - `timesheets.entries.list` — `perm="timesheets.entry.read"` — own-vs-all like the HTTP endpoint: `can_all = iam.has_permission(iam.permissions_for(user_id), "timesheets.entry.approve")`, then `[e.model_dump() for e in queries.entries_for(user_id, can_all)]`.
- `registry._import_optional(f"{manifest.package}.tools")` added to `import_module_code` (a module with no `tools.py` is fine).

- [ ] **Step 1: Write the failing tests**

```python
from django_tenants.utils import tenant_context
from easybiz.core.kernel import lifecycle
from easybiz.core.iam.models import Role, RolePermission, UserRole
from easybiz.core.tools import service
from easybiz.core.tools.registry import registry

def test_timesheets_tools_registered():
    t = registry.get("timesheets.projects.list")
    assert t is not None and t.module_id == "timesheets" and t.perm == "timesheets.project.read"

def test_projects_tool_runs_when_enabled(synced, db_tenant):
    lifecycle.enable_module(db_tenant, "timesheets")
    with tenant_context(db_tenant):
        role = Role.objects.create(name="r")
        RolePermission.objects.create(role=role, permission="timesheets.project.read")
        uid = "33333333-3333-3333-3333-333333333333"; UserRole.objects.create(user_id=uid, role=role)
        assert isinstance(service.invoke("timesheets.projects.list", {}, user_id=uid), list)

def test_timesheets_tool_gated_when_disabled(synced, db_tenant):
    import pytest
    with tenant_context(db_tenant):
        role = Role.objects.create(name="r")
        RolePermission.objects.create(role=role, permission="timesheets.project.read")
        uid = "44444444-4444-4444-4444-444444444444"; UserRole.objects.create(user_id=uid, role=role)
        with pytest.raises(service.ToolError) as e:
            service.invoke("timesheets.projects.list", {}, user_id=uid)  # timesheets not enabled
        assert e.value.status == 404
```

- [ ] **Step 2: Run them, verify they fail** — Run: `uv run pytest tests/test_timesheets_tools.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement** `timesheets/tools.py` and the `import_module_code` addition.
- [ ] **Step 4: Run them, verify they pass** — Expected: PASS.
- [ ] **Step 5: Commit** — `git add easybiz/modules/timesheets/tools.py easybiz/core/kernel/registry.py tests/test_timesheets_tools.py && git commit -m "Contribute Timesheets read tools (gated by enablement)"`

---

### Task 3: Contract-kit `check_tools`

**Files:**
- Modify: `easybiz/core/testing/checks.py` (add `check_tools`, wire into `_ALL_CHECKS`)
- Test: `tests/test_contract_check_tools.py`

**Interfaces:**
- Produces `check_tools(module_id) -> list[str]` (static; no harness): for each registered tool with `tool.module_id == module_id`:
  - name must start with `f"{module_id}."` else a failure;
  - `tool.perm` (if set) must be declared by the module (in the manifest's permission codes) or be a `core.*` permission, else a failure;
  - `tool.tier` must be a valid `ToolTier` (always true for a `Tool`, but assert to catch mis-registration).
- Added to `_ALL_CHECKS` so `run_module_contract_checks`/`check_module` cover it.

- [ ] **Step 1: Write the failing tests**

```python
import pytest
from easybiz.core.testing import checks
from easybiz.core.tools import registry as reg
from easybiz.core.tools.enums import ToolTier
from easybiz.core.tools.registry import Tool

def test_timesheets_tools_pass_check(synced):
    assert checks.check_tools("timesheets") == []

def test_undeclared_tool_permission_flagged(synced):
    reg.registry.register(Tool(name="timesheets.bad", description="d", tier=ToolTier.READ,
        perm="timesheets.secret", idempotent=True, input_schema=None,
        handler=lambda u, p: None, module_id="timesheets"))
    assert checks.check_tools("timesheets")  # non-empty: undeclared perm

def test_misprefixed_tool_name_flagged(synced):
    reg.registry.register(Tool(name="wrong.name", description="d", tier=ToolTier.READ,
        perm=None, idempotent=True, input_schema=None, handler=lambda u, p: None,
        module_id="timesheets"))
    assert checks.check_tools("timesheets")  # non-empty: bad prefix
```

- [ ] **Step 2: Run them, verify they fail** — Run: `uv run pytest tests/test_contract_check_tools.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement** `check_tools` and add it to `_ALL_CHECKS`.
- [ ] **Step 4: Run them, verify they pass** — Expected: PASS.
- [ ] **Step 5: Confirm the kit still passes on the real modules** — Run: `uv run pytest tests/test_module_contract.py -q` — Expected: PASS (timesheets + demo satisfy the contract incl. the new tool check).
- [ ] **Step 6: Run the full suite** — Run: `uv run pytest -q` — Expected: all pass.
- [ ] **Step 7: Commit** — `git add easybiz/core/testing/checks.py tests/test_contract_check_tools.py && git commit -m "Add check_tools to the module contract kit"`

---

## Post-implementation
- Update `README.md` Status with a short F23d paragraph (module-contributed tools gated by enablement; `check_tools`; Timesheets tools).
- **Security review before the PR** (standing instruction — tool gating is authorization): `/security-review` on the branch; fix High/Medium; then open the PR.
- Remaining F23 slices (noted): (b) agent keys + write tools [F13], (c) chatbot, (e) composite/shaping [F21], MCP wire server.
