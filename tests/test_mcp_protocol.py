from django_tenants.utils import tenant_context

from easybiz.core.iam.models import Role, RolePermission, UserRole
from easybiz.core.mcp import protocol
from easybiz.core.tools.service import Principal


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
    out = protocol.handle_message(
        {"jsonrpc": "2.0", "id": 2, "method": "ping"}, Principal.from_user("0")
    )
    assert out["result"] == {}


def test_unknown_method_is_method_not_found():
    out = protocol.handle_message(
        {"jsonrpc": "2.0", "id": 3, "method": "nope"}, Principal.from_user("0")
    )
    assert out["error"]["code"] == -32601 and out["id"] == 3


def test_notification_returns_none():
    # no "id" → a notification → no response
    assert (
        protocol.handle_message(
            {"jsonrpc": "2.0", "method": "notifications/initialized"}, Principal.from_user("0")
        )
        is None
    )


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
            {
                "jsonrpc": "2.0",
                "id": 5,
                "method": "tools/call",
                "params": {"name": "core.audit.list", "arguments": {}},
            },
            Principal.from_user(uid),
        )
        assert out["result"]["isError"] is False
        assert out["result"]["content"][0]["type"] == "text"


def test_tools_call_gate_failure_is_iserror_not_protocol_error(synced, db_tenant):
    with tenant_context(db_tenant):
        uid = _user("core.audit.read")  # lacks core.role.read
        out = protocol.handle_message(
            {
                "jsonrpc": "2.0",
                "id": 6,
                "method": "tools/call",
                "params": {"name": "core.roles.list", "arguments": {}},
            },
            Principal.from_user(uid),
        )
        assert "error" not in out  # a tool-gate denial is a result, not a JSON-RPC error
        assert out["result"]["isError"] is True


def test_tools_call_missing_name_is_invalid_params():
    out = protocol.handle_message(
        {"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {}}, Principal.from_user("0")
    )
    assert out["error"]["code"] == -32602  # invalid params
