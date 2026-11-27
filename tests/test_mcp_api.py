import json

from django.test import Client
from django_tenants.utils import tenant_context

from easybiz.core.iam.models import Role, RolePermission, UserRole
from easybiz.core.mcp.protocol import PROTOCOL_VERSION
from easybiz.core.tenancy.models import Tenant
from easybiz.core.users import service as users


def _owner(provision, slug):
    provision(slug=slug, modules=("timesheets",))
    return (
        Client()
        .post(
            "/api/auth/login",
            data={"email": f"owner@{slug}.test", "password": "change-me-now"},
            content_type="application/json",
            HTTP_HOST=f"{slug}.localhost",
        )
        .json()["access_token"]
    )


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
    return (
        Client()
        .post(
            "/api/core/apikeys",
            data=body,
            content_type="application/json",
            HTTP_HOST=f"{slug}.localhost",
            HTTP_AUTHORIZATION=f"Bearer {owner}",
        )
        .json()["secret"]
    )


def _rpc(raw, slug, payload):
    return Client().post(
        "/api/mcp",
        data=json.dumps(payload),
        content_type="application/json",
        HTTP_HOST=f"{slug}.localhost",
        HTTP_AUTHORIZATION=f"ApiKey {raw}",
    )


def _agent(owner, slug, uid, allowlist, perms=("core.audit.read",)):
    return _mint(
        owner, slug, permissions=list(perms), on_behalf_of_user=uid, tool_allowlist=allowlist
    )


def test_unauthenticated_mcp_is_401(synced, provision):
    provision(slug="m0", modules=())
    r = Client().post(
        "/api/mcp", data="{}", content_type="application/json", HTTP_HOST="m0.localhost"
    )
    assert r.status_code == 401


def test_initialize_over_http(synced, provision):
    owner = _owner(provision, "m1")
    uid = _user(Tenant.objects.get(slug="m1"), ["core.audit.read"], "u@m1.test")
    raw = _agent(owner, "m1", uid, ["core.audit.list"])
    r = _rpc(raw, "m1", {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert r.status_code == 200
    assert r.json()["result"]["protocolVersion"] == PROTOCOL_VERSION


def test_tools_call_over_http_success(synced, provision):
    owner = _owner(provision, "m2")
    uid = _user(Tenant.objects.get(slug="m2"), ["core.audit.read"], "u@m2.test")
    raw = _agent(owner, "m2", uid, ["core.audit.list"])
    r = _rpc(
        raw,
        "m2",
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "core.audit.list", "arguments": {}},
        },
    )
    assert r.status_code == 200 and r.json()["result"]["isError"] is False


def test_tools_call_outside_allowlist_is_iserror(synced, provision):
    owner = _owner(provision, "m3")
    uid = _user(Tenant.objects.get(slug="m3"), ["core.audit.read"], "u@m3.test")
    raw = _agent(owner, "m3", uid, ["core.audit.list"])
    r = _rpc(
        raw,
        "m3",
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "core.context", "arguments": {}},
        },
    )
    # not in allowlist → isError result, HTTP 200 (not a protocol error, not a raw 403)
    assert r.status_code == 200 and r.json()["result"]["isError"] is True


def test_notification_returns_202_no_body(synced, provision):
    owner = _owner(provision, "m4")
    uid = _user(Tenant.objects.get(slug="m4"), ["core.audit.read"], "u@m4.test")
    raw = _agent(owner, "m4", uid, ["core.audit.list"])
    r = _rpc(raw, "m4", {"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert r.status_code == 202 and not r.content


def test_malformed_body_is_parse_error(synced, provision):
    owner = _owner(provision, "m5")
    uid = _user(Tenant.objects.get(slug="m5"), ["core.audit.read"], "u@m5.test")
    raw = _agent(owner, "m5", uid, ["core.audit.list"])
    r = Client().post(
        "/api/mcp",
        data="{not json",
        content_type="application/json",
        HTTP_HOST="m5.localhost",
        HTTP_AUTHORIZATION=f"ApiKey {raw}",
    )
    assert r.status_code == 200
    assert r.json()["error"]["code"] == -32700 and r.json()["id"] is None
