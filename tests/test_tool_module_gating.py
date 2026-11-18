import pytest
from django_tenants.utils import tenant_context

from easybiz.core.iam.models import Role, RolePermission, UserRole
from easybiz.core.kernel import lifecycle
from easybiz.core.tools import registry as reg
from easybiz.core.tools import service
from easybiz.core.tools.enums import ToolTier
from easybiz.core.tools.registry import Tool


def _tool():
    reg.registry.register(
        Tool(
            name="demo.thing.list",
            description="d",
            tier=ToolTier.READ,
            perm=None,
            idempotent=True,
            input_schema=None,
            handler=lambda u, p: ["ok"],
            module_id="demo",
        )
    )


def _user(perms=()):
    role = Role.objects.create(name="r")
    RolePermission.objects.bulk_create([RolePermission(role=role, permission=p) for p in perms])
    uid = "22222222-2222-2222-2222-222222222222"
    UserRole.objects.create(user_id=uid, role=role)
    return uid


def test_module_tool_404_when_disabled(synced, db_tenant):
    with tenant_context(db_tenant):
        _tool()
        uid = _user()
        with pytest.raises(service.ToolError) as e:
            service.invoke("demo.thing.list", {}, user_id=uid)  # demo not enabled
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
