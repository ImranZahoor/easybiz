# F23b — Agent Tooling: Scoped Agent Keys + Write Tools — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an external agent drive the tool layer through a **scoped agent key** — bound to an on-behalf-of user, a tool allowlist, and a read/write scope — so it can invoke write tools within least privilege, every call gated by the same `authorize()`/ABAC the user has and audited as the key acting for that user.

**Architecture:** F13's `ApiKey` gains `on_behalf_of_user`, `tool_allowlist`, and `scope`. Tool invocation generalizes to a `Principal` (a **user**, from the JWT/chatbot path, or an **agent key**, from the `ApiKey` transport). The gate: tool ∈ allowlist → module enabled (404) → tier ≤ scope (write tools need `write`; `admin` hard-excluded from agents) → the key's permission subset allows the tool's perm → the on-behalf user's `authorize()` (RBAC+ABAC) grants it → validated inputs → audit (`actor = key, on behalf of user`). Effective authority is the **intersection** of the key's subset and the user's current permissions, so revoking either shrinks the agent instantly. A `tier=write` tool (`timesheets.projects.create`) proves the write path. The MCP wire server is a separate later effort.

**Tech Stack:** Python 3.13, Django 6.1, django-ninja/pydantic, stdlib, `uv`/pytest. No new dependencies.

**Spec:** `ERP-CORE-SPEC.md` §F23 items 3 (security by architecture) & 5b (agent keys + write tools). Builds on F13 (API keys), F14 (`authorize()`/ABAC), F23a/d (registry/transport/module tools). Honors F13's deferrals: validate key perms at creation (`_assert_assignable`), and gate tools through `authorize()`, not just RBAC.

## Global Constraints

- **Least privilege, deny-all:** an agent key's effective authority = its permission subset ∩ the on-behalf user's current `authorize()`; an empty/unset allowlist means **no tools**; `admin`/irreversible tools are never agent-invocable in this slice.
- **Never a full user token:** the agent key carries its own scope; it cannot exceed the on-behalf user's live permissions (role/ABAC changes apply immediately — no stale snapshot).
- **Same gate as HTTP:** the tool's permission is checked via `iam.authorize(subject_user, perm)` — the exact ABAC gate; nothing bypasses it. Tenant isolation is structural (the key lives in the tenant schema; it resolves only under that tenant's host).
- **Full audit:** every invocation records `actor = key id` with `on_behalf_of = user` for an agent, or the user for a JWT caller.
- Imports at top; `DomainError` mapping; no new deps. Per-key rate limiting and the MCP wire server are deferred (noted).

## Review Focus

- **Allowlist deny-all** — an agent key invoking a tool not in its allowlist is refused (403), and a key with an empty allowlist can invoke nothing. (Task 2/4.)
- **Scope gate** — a `read`-scope key cannot invoke a `write` tool (403); `admin` tools are refused for any agent. (Task 2/4.)
- **Intersection** — the agent is denied a tool the key's subset allows but the on-behalf user lacks, AND one the user has but the key's subset excludes. (Task 2/4.)
- **Live user authority** — revoking the on-behalf user's role (or an ABAC `deny_if`) immediately denies the agent, with no key change. (Task 2.)
- **Audit actor** — an agent invocation is audited with the key as actor and the user as on-behalf. (Task 2/4.)

---

### Task 1: Agent-key fields + validated creation

**Files:**
- Modify: `easybiz/core/iam/models.py` (ApiKey fields)
- Create: `easybiz/core/iam/migrations/0005_apikey_agent_fields.py`
- Modify: `easybiz/core/iam/service.py` (`create_api_key` gains the agent params + `_assert_assignable`)
- Modify: `easybiz/core/api/core_routes.py` + `easybiz/core/api/types.py` (expose the new fields on create/list)
- Test: `tests/test_agent_key.py`

**Interfaces:**
- `ApiKey` gains: `on_behalf_of_user = UUIDField(null=True, blank=True)`, `tool_allowlist = JSONField(default=list)`, `scope = CharField(max_length=5, default="read")`.
- `create_api_key(tenant, name, permissions, *, creator_id, creator_perms, expires_at=None, on_behalf_of_user=None, tool_allowlist=(), scope="read") -> tuple[ApiKey, str]` — now takes `tenant` (first positional) and the agent params; calls `_assert_assignable(tenant, perms)` (reject `*`/unknown/disabled — the F13 deferral) **before** `_assert_grantable`; validates `scope in {"read","write"}` (else `ApiKeyError`); stores the allowlist and on-behalf user. (Update F13's call site + tests to pass `tenant`.)
- `ApiKeyIn` gains `on_behalf_of_user: str | None = None`, `tool_allowlist: list[str] = []`, `scope: str = "read"`; `ApiKeyOut` gains `on_behalf_of_user`, `tool_allowlist`, `scope`.

- [ ] **Step 1: Write the failing tests**

```python
import pytest
from django_tenants.utils import tenant_context
from easybiz.core.iam import service as iam
CREATOR = "11111111-1111-1111-1111-111111111111"
USER = "22222222-2222-2222-2222-222222222222"

def test_create_agent_key_stores_scope_allowlist_user(synced, db_tenant):
    with tenant_context(db_tenant):
        key, _ = iam.create_api_key(db_tenant, "agent", ["core.audit.read"], creator_id=CREATOR,
            creator_perms={"*"}, on_behalf_of_user=USER, tool_allowlist=["core.audit.list"], scope="write")
        assert key.on_behalf_of_user is not None and key.scope == "write"
        assert key.tool_allowlist == ["core.audit.list"]

def test_create_rejects_unknown_permission(synced, db_tenant):
    with tenant_context(db_tenant):
        with pytest.raises(iam.ApiKeyError):
            iam.create_api_key(db_tenant, "k", ["made.up.perm"], creator_id=CREATOR, creator_perms={"*"})

def test_create_rejects_bad_scope(synced, db_tenant):
    with tenant_context(db_tenant):
        with pytest.raises(iam.ApiKeyError):
            iam.create_api_key(db_tenant, "k", [], creator_id=CREATOR, creator_perms=None, scope="admin")
```

- [ ] **Step 2: Run them, verify they fail** — Run: `uv run pytest tests/test_agent_key.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement** the model fields + migration, the `create_api_key` changes (thread `tenant`, `_assert_assignable`, scope validation, agent params), and the type/handler fields. Update F13's `create_api_key` call site in `core_routes.py` and its tests to pass `request.tenant` / `db_tenant`.
- [ ] **Step 4: Run them + F13's suite + migration check** — Run: `uv run pytest tests/test_agent_key.py tests/test_apikey_service.py tests/test_apikey_api.py -q && uv run manage.py makemigrations --check --dry-run` — Expected: PASS + "No changes detected".
- [ ] **Step 5: Commit** — `git add -A && git commit -m "Add agent-key fields (on-behalf user, allowlist, scope) and validate perms at creation"`

---

### Task 2: Principal + generalized, ABAC-gated invocation

**Files:**
- Modify: `easybiz/core/tools/service.py`
- Test: `tests/test_tool_principal.py`

**Interfaces:**
- Produces `service.Principal` (dataclass): `subject_user_id`, `scope: str`, `allowlist: set[str] | None`, `actor_id`, `on_behalf_of`, `key_perms: set[str] | None`.
  - `Principal.from_user(user_id)` → `scope="write"`, `allowlist=None`, `actor_id=user_id`, `on_behalf_of=None`, `key_perms=None`.
  - `Principal.from_agent_key(key)` → `subject_user_id=key.on_behalf_of_user`, `scope=key.scope`, `allowlist=set(key.tool_allowlist)`, `actor_id=key.id`, `on_behalf_of=key.on_behalf_of_user`, `key_perms=set(key.permissions)`.
- `_invoke(name, raw_inputs, principal) -> object` — the gate, in order: `registry.get` or 404 → `_enabled` or 404 → `allowlist is not None and name not in allowlist` → 403 → `tool.tier is ADMIN` → 403 → `tool.tier is WRITE and scope != "write"` → 403 → `key_perms is not None and tool.perm and not has_permission(key_perms, tool.perm)` → 403 → `tool.perm and not iam.authorize(subject_user_id, tool.perm)` → 403 → validate inputs (as today) → `tool.handler(subject_user_id, params)` → `audit.record(actor_id, "tool.invoked", entity="tool", entity_id=name, after={"on_behalf_of": str(on_behalf_of)} if on_behalf_of else None)`.
- `accessible_for(principal) -> list[Tool]` — `_enabled` AND allowlist AND tier-vs-scope (admin excluded) AND key-subset AND `has_permission(permissions_for(subject), tool.perm)` (RBAC for discovery; `authorize` is the invoke-time gate).
- Backward-compatible wrappers: `invoke(name, inputs, *, user_id)` → `_invoke(name, inputs, Principal.from_user(user_id))`; `accessible(user_id)` → `accessible_for(Principal.from_user(user_id))`. (The perm check upgrades from `has_permission` to `authorize`; existing read-tool tests, which have no ABAC policies, are unaffected.)

- [ ] **Step 1: Write the failing tests** (build principals directly; a throwaway write tool + an agent key via `ApiKey`)

```python
import pytest
from django_tenants.utils import tenant_context
from ninja import Schema
from easybiz.core.iam.models import ApiKey, Role, RolePermission, UserRole, Policy
from easybiz.core.iam.enums import PolicyEffect
from easybiz.core.tools import registry as reg, service
from easybiz.core.tools.enums import ToolTier
from easybiz.core.tools.registry import Tool

USER = "22222222-2222-2222-2222-222222222222"

def _user_with(perms):
    role = Role.objects.create(name="r")
    RolePermission.objects.bulk_create([RolePermission(role=role, permission=p) for p in perms])
    UserRole.objects.create(user_id=USER, role=role)

def _reg(name, tier=ToolTier.READ, perm="core.audit.read"):
    reg.registry.register(Tool(name=name, description="d", tier=tier, perm=perm, idempotent=True,
        input_schema=None, handler=lambda u, p: {"ok": name}))

def _agent(scope="read", allowlist=("core.read",), key_perms=("core.audit.read",)):
    return service.Principal(subject_user_id=USER, scope=scope, allowlist=set(allowlist),
        actor_id="99999999-9999-9999-9999-999999999999", on_behalf_of=USER, key_perms=set(key_perms))

def test_allowlist_denies(synced, db_tenant):
    with tenant_context(db_tenant):
        _user_with(["core.audit.read"]); _reg("core.read")
        with pytest.raises(service.ToolError) as e:
            service._invoke("core.read", {}, _agent(allowlist=["other"]))  # not in allowlist
        assert e.value.status == 403

def test_read_scope_denies_write_tool(synced, db_tenant):
    with tenant_context(db_tenant):
        _user_with(["core.audit.read"]); _reg("core.write", tier=ToolTier.WRITE)
        with pytest.raises(service.ToolError) as e:
            service._invoke("core.write", {}, _agent(allowlist=["core.write"]))  # read scope
        assert e.value.status == 403

def test_intersection_user_lacks(synced, db_tenant):
    with tenant_context(db_tenant):
        _user_with([])  # user holds nothing
        _reg("core.read")
        with pytest.raises(service.ToolError):  # key allows it but authorize(user) denies
            service._invoke("core.read", {}, _agent())

def test_intersection_key_excludes(synced, db_tenant):
    with tenant_context(db_tenant):
        _user_with(["core.audit.read"]); _reg("core.read")
        with pytest.raises(service.ToolError):  # user has it but the key's subset doesn't
            service._invoke("core.read", {}, _agent(key_perms=["core.user.read"]))

def test_agent_invokes_when_both_grant_and_audits(synced, db_tenant):
    from easybiz.core.audit.models import AuditLog
    with tenant_context(db_tenant):
        _user_with(["core.audit.read"]); _reg("core.read")
        assert service._invoke("core.read", {}, _agent())["ok"] == "core.read"
        row = AuditLog.objects.get(action="tool.invoked", entity_id="core.read")
        assert row.actor_id is not None  # key as actor

def test_abac_deny_blocks_agent(synced, db_tenant):
    with tenant_context(db_tenant):
        _user_with(["core.audit.read"]); _reg("core.read")
        Policy.objects.create(permission="core.audit.read", effect=PolicyEffect.DENY_IF,
            condition={"op": "eq", "left": {"var": "context.x"}, "right": 1})  # a matching deny
        # with resource/context empty the deny won't fire; use an always-true deny instead:
        Policy.objects.create(permission="core.audit.read", effect=PolicyEffect.DENY_IF,
            condition={"op": "eq", "left": 1, "right": 1})
        with pytest.raises(service.ToolError):
            service._invoke("core.read", {}, _agent())
```

- [ ] **Step 2: Run them, verify they fail** — Run: `uv run pytest tests/test_tool_principal.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement** `Principal`, `_invoke`, `accessible_for`, and the wrappers. (`iam.authorize` takes `resource`/`context` defaulting to `{}`; tool invocation passes none.)
- [ ] **Step 4: Run them + the existing tool tests** — Run: `uv run pytest tests/test_tool_principal.py tests/test_tool_invoke.py tests/test_core_tools.py tests/test_tool_module_gating.py tests/test_timesheets_tools.py -q` — Expected: PASS.
- [ ] **Step 5: Commit** — `git add easybiz/core/tools/service.py tests/test_tool_principal.py && git commit -m "Generalize tool invocation to a Principal with allowlist/scope + authorize() gating"`

---

### Task 3: A write tool (timesheets.projects.create)

**Files:**
- Modify: `easybiz/modules/timesheets/tools.py`
- Test: `tests/test_timesheets_write_tool.py`

**Interfaces:**
- Register `timesheets.projects.create` — `tier=WRITE`, `perm="timesheets.project.manage"`, `module_id="timesheets"`, `input_schema=ProjectIn` (code, name), handler: `commands.create_project(CreateProjectParams(actor_id=user_id, **params.model_dump())).model_dump()`.

- [ ] **Step 1: Write the failing tests**

```python
from django_tenants.utils import tenant_context
from easybiz.core.kernel import lifecycle
from easybiz.core.iam.models import Role, RolePermission, UserRole
from easybiz.core.tools import service
from easybiz.core.tools.enums import ToolTier
from easybiz.core.tools.registry import registry

def test_write_tool_registered():
    t = registry.get("timesheets.projects.create")
    assert t is not None and t.tier == ToolTier.WRITE and t.perm == "timesheets.project.manage"

def test_user_can_create_project_via_tool(synced, db_tenant):
    lifecycle.enable_module(db_tenant, "timesheets")
    with tenant_context(db_tenant):
        role = Role.objects.create(name="r")
        RolePermission.objects.create(role=role, permission="timesheets.project.manage")
        uid = "33333333-3333-3333-3333-333333333333"; UserRole.objects.create(user_id=uid, role=role)
        out = service.invoke("timesheets.projects.create", {"code": "abc", "name": "ABC"}, user_id=uid)
        assert out["code"] == "ABC"
```

- [ ] **Step 2: Run them, verify they fail** — Run: `uv run pytest tests/test_timesheets_write_tool.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement** the write tool.
- [ ] **Step 4: Run them + the contract kit** — Run: `uv run pytest tests/test_timesheets_write_tool.py tests/test_module_contract.py -q` — Expected: PASS (`check_tools` still passes: the new tool is prefixed + uses a declared perm).
- [ ] **Step 5: Commit** — `git add easybiz/modules/timesheets/tools.py tests/test_timesheets_write_tool.py && git commit -m "Add a write tool (timesheets.projects.create) over the command layer"`

---

### Task 4: ApiKey transport auth on /api/tools

**Files:**
- Create: `easybiz/core/api/agent_auth.py` (a Ninja auth that resolves a JWT user or an `ApiKey` to a `Principal`)
- Modify: `easybiz/core/api/tools_routes.py` (use the new auth + principal)
- Test: `tests/test_agent_tools_api.py`

**Interfaces:**
- `agent_auth.ToolPrincipalAuth` — a callable Ninja auth: reads `Authorization`; `Bearer <jwt>` → resolve the active tenant member (reuse `TenantJWTAuth._user_from_token`) → `Principal.from_user(user.id)`; `ApiKey <prefix>.<secret>` → `iam.authenticate_api_key(raw)`; if the key resolves **and** has an `on_behalf_of_user` (service keys without one are refused on this transport) → `Principal.from_agent_key(key)`; else `None` (401). Sets `request.auth` to the `Principal`.
- `tools_routes` endpoints switch to this auth and use `request.auth` (a `Principal`): `list_tools` → `service.accessible_for(request.auth)`; `describe_tool` → gate with `accessible_for`; `invoke_tool` → `service._invoke(name, body, request.auth)`.

- [ ] **Step 1: Write the failing tests** (create an agent key for an on-behalf user, send `Authorization: ApiKey …`)

```python
# helpers: _owner(provision, slug) -> owner JWT; make an agent key for a scoped user via the service.
def _agent_key(tenant, *, perms, user_id, allowlist, scope):
    from easybiz.core.iam import service as iam
    with tenant_context(tenant):
        _, raw = iam.create_api_key(tenant, "agent", perms, creator_id=OWNER_ID, creator_perms={"*"},
            on_behalf_of_user=user_id, tool_allowlist=allowlist, scope=scope)
        return raw

def _akreq(method, path, raw, slug, body=None):
    kw = {"HTTP_HOST": f"{slug}.localhost", "HTTP_AUTHORIZATION": f"ApiKey {raw}"}
    ...  # like _req but ApiKey scheme

def test_agent_key_lists_only_allowlisted(synced, provision): ...   # list shows only allowlisted+authorized
def test_agent_key_invokes_read_tool_in_scope(synced, provision): ... # 200
def test_agent_key_read_scope_refused_write_tool(synced, provision): ... # 403
def test_agent_key_write_scope_creates_project(synced, provision): ...   # 200, project created
def test_tool_not_in_allowlist_403(synced, provision): ...              # 403
def test_service_key_without_onbehalf_rejected(synced, provision): ...   # 401/403
```

(Flesh out: provision a tenant with timesheets; create a scoped user holding the needed perms; mint agent keys with varying scope/allowlist; assert the gates. Reuse `encode_tenant_token` only for the owner setup.)

- [ ] **Step 2: Run them, verify they fail** — Run: `uv run pytest tests/test_agent_tools_api.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement** `agent_auth.py` and switch `tools_routes` to it + principals.
- [ ] **Step 4: Run them + the F23a transport tests** — Run: `uv run pytest tests/test_agent_tools_api.py tests/test_tools_api.py -q` — Expected: PASS (JWT callers still work via `Principal.from_user`).
- [ ] **Step 5: Run the full suite** — Run: `uv run pytest -q` — Expected: all pass.
- [ ] **Step 6: Commit** — `git add -A && git commit -m "Authenticate /api/tools with agent keys (scoped Principal)"`

---

## Post-implementation
- Update `README.md` Status with a short F23b paragraph (scoped agent keys: on-behalf user + allowlist + read/write scope; write tools; intersection + authorize() gate; `ApiKey` transport on `/api/tools`).
- **Security review before the PR** (standing instruction — agent authorization + write access): `/security-review` on the branch; fix High/Medium; then open the PR.
- Deferred (noted): per-key rate limiting; the MCP stdio/streamable-HTTP wire server; `admin`-tier elevation + human confirmation; F23c (chatbot) and F23e (composite/shaping, F21).
