# F23f — MCP Wire Server (streamable-HTTP) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose the existing easybiz tool layer over the Model Context Protocol as a hand-rolled JSON-RPC 2.0 endpoint at `/api/mcp`, so an external agent can `initialize`, enumerate (`tools/list`), and invoke (`tools/call`) exactly the tools its scoped agent key already permits — with no new authz surface and no business logic re-implemented.

**Architecture:** A transport-free dispatch core (`easybiz/core/mcp/protocol.py`) turns one parsed JSON-RPC message + a `Principal` into one response (or `None` for a notification), delegating `tools/list` to `service.accessible_for` and `tools/call` to `service._invoke`. A thin django-ninja route (`easybiz/core/api/mcp_routes.py`) is the only transport piece: it reuses `ToolPrincipalAuth` (HTTP-level auth → `Principal`) and `TenantMainMiddleware` (tenant from host), parses the body, and hands the message to the core. The full F23b gate (allowlist → tier/scope → key-subset → `authorize` → validate) and the audit entry are inherited unchanged because `tools/call` bottoms out in `service._invoke`.

**Tech Stack:** Python 3.13, Django 6.1, django-ninja/pydantic, django-tenants, `uv`/pytest on real PostgreSQL. No new dependencies (JSON-RPC framing is hand-rolled, consistent with the project's hand-rolled manifest-v2 validation).

**Spec:** `ERP-CORE-SPEC.md` §F23 — "`easybiz/core/mcp/`, stdio + streamable-HTTP"; "one tool layer, many transports … both enumerate the *same* registry"; security-by-architecture (every invocation gated by the tool's `perm()`, scoped agent key, tenant isolation, full audit). This plan delivers the **streamable-HTTP** transport only; see Non-goals.

## Global Constraints

- No new third-party dependencies; hand-roll the JSON-RPC 2.0 framing.
- Imports at top of file (project rule); no inline imports in non-test code.
- One tool layer: `tools/list`/`tools/call` go through `service.accessible_for`/`service._invoke` — no tool logic, no gate logic, and no audit call is duplicated in the MCP layer.
- Tenant isolation and identity/scope are inherited from the existing `TenantMainMiddleware` + `ToolPrincipalAuth`; the MCP layer adds no new way to reach a tenant or to become a principal.
- The endpoint mounts under the existing NinjaAPI prefix, so its URL is `/api/mcp` (the api is mounted at `/api/` in `config/urls.py`).

## Non-goals (deferred to later F23 slices)

- stdio transport (needs a separate management-command entrypoint that cannot carry HTTP headers).
- SSE / streaming responses and server→client notifications (`notifications/*` outbound); `Accept: text/event-stream` is answered with a single JSON response.
- The `search_tools`/`describe_tool` lazy-discovery meta-toolset and MCP `resources`/`prompts`.
- JSON-RPC batch arrays (removed in current MCP revisions): a top-level JSON array is rejected as one Invalid Request.

## Review Focus

- **Unauthenticated POST** — a `/api/mcp` call with no/invalid `Authorization` is refused at the transport (HTTP 401) before any JSON-RPC parsing; no tool list or schema leaks. (Task 2.)
- **Malformed JSON body** — a non-JSON or truncated body returns a JSON-RPC parse error (`code -32700`, `id: null`) with HTTP 200, not a Django 500. (Task 2.)
- **Unknown method** — `method` not in {initialize, ping, tools/list, tools/call} returns JSON-RPC `-32601` (method not found), not a 500. (Task 1.)
- **Gate failure inside tools/call** — a tool blocked by allowlist/scope/perm (a `DomainError` from `_invoke`) is reported as an MCP tool result `{content, isError: true}`, not as a JSON-RPC protocol error and not as a raw HTTP 403; tenant isolation is unaffected. (Task 1.)
- **Notification (no `id`)** — a message without an `id` (e.g. `notifications/initialized`) produces no JSON-RPC response body (HTTP 202), not an error and not a spurious result. (Task 2 at the wire, Task 1 for the `None` return.)

---

### Task 1: JSON-RPC dispatch core (`easybiz/core/mcp/protocol.py`)

Pure dispatch over a single parsed message + a `Principal`. No HTTP, no request object. This is the whole protocol behavior and is independently testable with a `Principal.from_user(uid)` inside `tenant_context`.

**Files:**
- Create: `easybiz/core/mcp/__init__.py` (empty package marker)
- Create: `easybiz/core/mcp/protocol.py`
- Test: `tests/test_mcp_protocol.py`

**Interfaces:**
- Consumes: `easybiz.core.tools.service` — `accessible_for(principal) -> list[Tool]`, `_invoke(name, raw_inputs, principal) -> object`, `ToolError`/`DomainError`; `easybiz.core.tools.registry.Tool` (`.name`, `.description`, `.input_schema` is a `type[BaseModel] | None`); `django.conf.settings.EASYBIZ_CORE_VERSION`; `easybiz.core.errors.DomainError`.
- Produces:
  - `PROTOCOL_VERSION: str = "2025-06-18"` and `SERVER_INFO: dict = {"name": "easybiz", "version": settings.EASYBIZ_CORE_VERSION}` (build `SERVER_INFO` at call time so the setting is read live, see Step 3).
  - `handle_message(message: dict, principal) -> dict | None` — returns a JSON-RPC response dict, or `None` when `message` is a notification (no `id`). Never raises for protocol-level problems (returns a JSON-RPC error dict); never raises `DomainError` out of `tools/call` (maps it to an `isError` result).
  - `tool_descriptor(tool) -> dict` — `{"name", "description", "inputSchema"}`, where `inputSchema` is `tool.input_schema.model_json_schema()` or `{"type": "object", "properties": {}}` when the tool has no input schema.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_mcp_protocol.py
from django_tenants.utils import tenant_context
from easybiz.core.iam.models import Role, RolePermission, UserRole
from easybiz.core.tools.service import Principal
from easybiz.core.mcp import protocol


def _user(perm):
    role = Role.objects.create(name="r")
    RolePermission.objects.create(role=role, permission=perm)
    uid = "55555555-5555-5555-5555-555555555555"
    UserRole.objects.create(user_id=uid, role=role)
    return uid


def test_initialize_returns_handshake():
    msg = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
    out = protocol.handle_message(msg, Principal.from_user("00000000-0000-0000-0000-000000000000"))
    assert out["id"] == 1 and out["jsonrpc"] == "2.0"
    assert out["result"]["protocolVersion"] == protocol.PROTOCOL_VERSION
    assert out["result"]["serverInfo"]["name"] == "easybiz"
    assert "tools" in out["result"]["capabilities"]


def test_ping_returns_empty_result():
    out = protocol.handle_message({"jsonrpc": "2.0", "id": 2, "method": "ping"}, Principal.from_user("0"))
    assert out["result"] == {}


def test_unknown_method_is_method_not_found():
    out = protocol.handle_message({"jsonrpc": "2.0", "id": 3, "method": "nope"}, Principal.from_user("0"))
    assert out["error"]["code"] == -32601 and "id" in out and out["id"] == 3


def test_notification_returns_none():
    # no "id" → a notification → no response
    assert protocol.handle_message({"jsonrpc": "2.0", "method": "notifications/initialized"}, Principal.from_user("0")) is None


def test_tools_list_reflects_accessible(synced, db_tenant):
    with tenant_context(db_tenant):
        uid = _user("core.audit.read")
        out = protocol.handle_message(
            {"jsonrpc": "2.0", "id": 4, "method": "tools/list"}, Principal.from_user(uid)
        )
        names = {t["name"] for t in out["result"]["tools"]}
        assert "core.audit.list" in names
        audit = next(t for t in out["result"]["tools"] if t["name"] == "core.audit.list")
        assert audit["inputSchema"]["type"] == "object"  # JSON Schema, not a pydantic class


def test_tools_call_success_wraps_result(synced, db_tenant):
    with tenant_context(db_tenant):
        uid = _user("core.audit.read")
        out = protocol.handle_message(
            {"jsonrpc": "2.0", "id": 5, "method": "tools/call",
             "params": {"name": "core.audit.list", "arguments": {}}},
            Principal.from_user(uid),
        )
        assert out["result"]["isError"] is False
        assert out["result"]["content"][0]["type"] == "text"


def test_tools_call_gate_failure_is_iserror_not_protocol_error(synced, db_tenant):
    with tenant_context(db_tenant):
        uid = _user("core.audit.read")  # lacks core.role.read
        out = protocol.handle_message(
            {"jsonrpc": "2.0", "id": 6, "method": "tools/call",
             "params": {"name": "core.roles.list", "arguments": {}}},
            Principal.from_user(uid),
        )
        assert "error" not in out  # a tool-gate denial is a result, not a JSON-RPC error
        assert out["result"]["isError"] is True


def test_tools_call_missing_name_is_invalid_params():
    out = protocol.handle_message(
        {"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {}}, Principal.from_user("0")
    )
    assert out["error"]["code"] == -32602  # invalid params
```

- [ ] **Step 2: Run them, verify they fail** — Run: `uv run pytest tests/test_mcp_protocol.py -q` — Expected: FAIL (module `easybiz.core.mcp` does not exist).

- [ ] **Step 3: Implement `protocol.py`**

  Signatures and the dispatch contract:
  - `PROTOCOL_VERSION = "2025-06-18"`. Build server info live: a helper `_server_info() -> dict` returning `{"name": "easybiz", "version": settings.EASYBIZ_CORE_VERSION}` (don't freeze the setting at import).
  - JSON-RPC builders: `_result(id_, result) -> {"jsonrpc": "2.0", "id": id_, "result": result}` and `_error(id_, code, message) -> {"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": message}}`.
  - `handle_message(message, principal)`:
    - If `message` is not a dict or lacks a string `"method"` → `_error(message.get("id"), -32600, ...)` (Invalid Request).
    - If `"id"` not in `message` → it's a notification: dispatch for side effects if any, then return `None` (in this slice, all supported notifications are no-ops, so just return `None`).
    - Dispatch on `method`:
      - `"initialize"` → `_result(id_, {"protocolVersion": PROTOCOL_VERSION, "capabilities": {"tools": {"listChanged": False}}, "serverInfo": _server_info()})`.
      - `"ping"` → `_result(id_, {})`.
      - `"tools/list"` → `_result(id_, {"tools": [tool_descriptor(t) for t in service.accessible_for(principal)]})`.
      - `"tools/call"` → read `params = message.get("params") or {}`; `name = params.get("name")`; if not a non-empty str → `_error(id_, -32602, "missing tool name")`; `arguments = params.get("arguments") or {}`; then `try: result = service._invoke(name, arguments, principal)` → `_result(id_, {"content": [{"type": "text", "text": json.dumps(result, default=str)}], "isError": False})`; `except DomainError as exc:` → `_result(id_, {"content": [{"type": "text", "text": str(exc)}], "isError": True})`.
      - else → `_error(id_, -32601, f"method not found: {method}")`.
  - `tool_descriptor(tool)` as specified in Interfaces.
  - Note: `DomainError` from `_invoke` (unknown tool 404, not-allowlisted 403, scope 403, perm 403, invalid input 422) all collapse to the same `isError` result shape — that is the intended MCP behavior (tool-level failures are results). Protocol-level problems (bad method, bad params) are JSON-RPC errors.

- [ ] **Step 4: Run them, verify they pass** — Run: `uv run pytest tests/test_mcp_protocol.py -q` — Expected: PASS.

- [ ] **Step 5: Commit** — `git add -A && git commit -m "Add MCP JSON-RPC dispatch core over the tool service"`

---

### Task 2: HTTP transport route (`easybiz/core/api/mcp_routes.py`) + mount

The only transport piece. A single authed POST that parses the body, calls the core, and shapes the HTTP response (200 with the JSON-RPC response, 202 for a notification, 200 with a parse-error envelope for bad JSON). Auth and tenant come from the existing middleware/auth — no new identity code.

**Files:**
- Create: `easybiz/core/api/mcp_routes.py`
- Modify: `easybiz/core/api/__init__.py` (import `mcp_router`; `api.add_router("/mcp", mcp_router)`)
- Test: `tests/test_mcp_api.py`

**Interfaces:**
- Consumes: `easybiz.core.api.agent_auth.tool_principal` (auth → `request.auth` is a `Principal`, else ninja returns 401); `easybiz.core.mcp.protocol.handle_message` and `PROTOCOL_VERSION` (Task 1); `ninja.Router`; `django.http.HttpResponse`.
- Produces: `router` (a `ninja.Router`) with one operation `POST ""` (so the mounted path is `/api/mcp`), `auth=tool_principal`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_mcp_api.py
import json
from django.test import Client
from django_tenants.utils import tenant_context
from easybiz.core.iam.models import Role, RolePermission, UserRole
from easybiz.core.tenancy.models import Tenant
from easybiz.core.users import service as users


def _owner(provision, slug):
    provision(slug=slug, modules=("timesheets",))
    return Client().post(
        "/api/auth/login",
        data={"email": f"owner@{slug}.test", "password": "change-me-now"},
        content_type="application/json", HTTP_HOST=f"{slug}.localhost",
    ).json()["access_token"]


def _user(tenant, perms, email):
    with tenant_context(tenant):
        role = Role.objects.create(name=f"r-{email}")
        RolePermission.objects.bulk_create([RolePermission(role=role, permission=p) for p in perms])
        u = users.create_user(email, tenant, password="change-me-now")
        UserRole.objects.create(user_id=u.id, role=role)
        return str(u.id)


def _mint(owner, slug, **over):
    body = {"name": "agent", "scope": "read"}
    body.update(over)
    return Client().post(
        "/api/core/apikeys", data=body, content_type="application/json",
        HTTP_HOST=f"{slug}.localhost", HTTP_AUTHORIZATION=f"Bearer {owner}",
    ).json()["secret"]


def _rpc(raw, slug, payload):
    return Client().post(
        "/api/mcp", data=json.dumps(payload), content_type="application/json",
        HTTP_HOST=f"{slug}.localhost", HTTP_AUTHORIZATION=f"ApiKey {raw}",
    )


def test_unauthenticated_mcp_is_401(synced, provision):
    provision(slug="m0", modules=())
    r = Client().post("/api/mcp", data="{}", content_type="application/json", HTTP_HOST="m0.localhost")
    assert r.status_code == 401


def test_initialize_over_http(synced, provision):
    owner = _owner(provision, "m1")
    uid = _user(Tenant.objects.get(slug="m1"), ["core.audit.read"], "u@m1.test")
    raw = _mint(owner, "m1", permissions=["core.audit.read"], on_behalf_of_user=uid,
                tool_allowlist=["core.audit.list"])
    r = _rpc(raw, "m1", {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert r.status_code == 200
    from easybiz.core.mcp.protocol import PROTOCOL_VERSION
    assert r.json()["result"]["protocolVersion"] == PROTOCOL_VERSION


def test_tools_call_over_http_success(synced, provision):
    owner = _owner(provision, "m2")
    uid = _user(Tenant.objects.get(slug="m2"), ["core.audit.read"], "u@m2.test")
    raw = _mint(owner, "m2", permissions=["core.audit.read"], on_behalf_of_user=uid,
                tool_allowlist=["core.audit.list"])
    r = _rpc(raw, "m2", {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                         "params": {"name": "core.audit.list", "arguments": {}}})
    assert r.status_code == 200 and r.json()["result"]["isError"] is False


def test_tools_call_outside_allowlist_is_iserror(synced, provision):
    owner = _owner(provision, "m3")
    uid = _user(Tenant.objects.get(slug="m3"), ["core.audit.read"], "u@m3.test")
    raw = _mint(owner, "m3", permissions=["core.audit.read"], on_behalf_of_user=uid,
                tool_allowlist=["core.audit.list"])
    r = _rpc(raw, "m3", {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                         "params": {"name": "core.context", "arguments": {}}})
    assert r.status_code == 200 and r.json()["result"]["isError"] is True  # not in allowlist → isError, HTTP 200


def test_notification_returns_202_no_body(synced, provision):
    owner = _owner(provision, "m4")
    uid = _user(Tenant.objects.get(slug="m4"), ["core.audit.read"], "u@m4.test")
    raw = _mint(owner, "m4", permissions=["core.audit.read"], on_behalf_of_user=uid,
                tool_allowlist=["core.audit.list"])
    r = _rpc(raw, "m4", {"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert r.status_code == 202 and not r.content


def test_malformed_body_is_parse_error(synced, provision):
    owner = _owner(provision, "m5")
    uid = _user(Tenant.objects.get(slug="m5"), ["core.audit.read"], "u@m5.test")
    raw = _mint(owner, "m5", permissions=["core.audit.read"], on_behalf_of_user=uid,
                tool_allowlist=["core.audit.list"])
    r = Client().post("/api/mcp", data="{not json", content_type="application/json",
                      HTTP_HOST="m5.localhost", HTTP_AUTHORIZATION=f"ApiKey {raw}")
    assert r.status_code == 200 and r.json()["error"]["code"] == -32700 and r.json()["id"] is None
```

- [ ] **Step 2: Run them, verify they fail** — Run: `uv run pytest tests/test_mcp_api.py -q` — Expected: FAIL (`/api/mcp` is 404 / router not mounted).

- [ ] **Step 3: Implement `mcp_routes.py` and mount it**

  - `router = Router()`. One operation:
    ```python
    @router.post("", auth=tool_principal)
    def rpc(request):
        try:
            message = json.loads(request.body or b"{}")
        except json.JSONDecodeError:
            return {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
        response = protocol.handle_message(message, request.auth)
        if response is None:
            return HttpResponse(status=202)   # a notification: accepted, no body
        return response
    ```
    - The parse-error branch returns a dict → ninja serializes it as HTTP 200 JSON (the JSON-RPC envelope carries the error; HTTP stays 200, matching the parse-error test).
    - Returning a dict → HTTP 200 JSON; returning `HttpResponse(status=202)` → empty 202.
    - `auth=tool_principal`: an unresolved principal makes ninja return 401 before the body is read — satisfies the unauthenticated test and keeps the handshake itself authenticated.
  - Mount in `easybiz/core/api/__init__.py`: `from easybiz.core.api.mcp_routes import router as mcp_router` and `api.add_router("/mcp", mcp_router)` alongside the existing routers.

- [ ] **Step 4: Run them, verify they pass** — Run: `uv run pytest tests/test_mcp_api.py -q` — Expected: PASS.

- [ ] **Step 5: Run the adjacent suites** — Run: `uv run pytest tests/test_mcp_protocol.py tests/test_mcp_api.py tests/test_agent_tools_api.py tests/test_tool_principal.py -q` — Expected: PASS (the MCP transport did not change the HTTP tool transport or the auth path).

- [ ] **Step 6: Full suite + lint + types** — Run: `uv run pytest -q && uv run ruff check easybiz/core/mcp easybiz/core/api/mcp_routes.py tests/test_mcp_protocol.py tests/test_mcp_api.py && uv run mypy easybiz/core/mcp easybiz/core/api/mcp_routes.py` — Expected: all green.

- [ ] **Step 7: Commit** — `git add -A && git commit -m "Expose the tool layer over MCP streamable-HTTP at /api/mcp"`

---

## Post-implementation

- Update `README.md` Status with a short F23f paragraph: MCP streamable-HTTP at `/api/mcp`; `initialize`/`ping`/`tools/list`/`tools/call`; same registry, same F23b gate, same audit as the HTTP tool transport; tenant + agent-key auth reused; stdio / SSE / meta-toolset deferred.
- No new events, no migrations.
- **Reviews:** a standard whole-branch review **and** a security review — this is an authentication/authorization-exposing transport surface (per the standing instruction to security-review auth/authz work before the PR). The security review must confirm: no path reaches a tool bypassing `_invoke`'s gate; no principal can be formed that `ToolPrincipalAuth` wouldn't form for the HTTP transport; tenant isolation holds over the wire; the handshake itself is authenticated (no unauthenticated `initialize`); and gate denials never leak more than the HTTP transport already does.
