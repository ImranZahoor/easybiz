from django_tenants.utils import tenant_context

from easybiz.core.tools import service
from easybiz.core.tools.enums import ToolTier
from easybiz.core.tools.registry import registry

CORE_TOOLS = {
    "core.context",
    "core.modules.list",
    "core.roles.list",
    "core.permissions.list",
    "core.users.list",
    "core.audit.list",
}


def test_core_tools_registered():
    names = {t.name for t in registry.all()}
    assert CORE_TOOLS <= names
    assert registry.get("core.audit.list").perm == "core.audit.read"
    assert all(t.tier == ToolTier.READ for t in registry.all() if t.name in CORE_TOOLS)


def test_context_tool_runs_for_any_user(synced, db_tenant):
    from easybiz.core.iam.models import Role, UserRole

    with tenant_context(db_tenant):
        role = Role.objects.create(name="r")
        uid = "33333333-3333-3333-3333-333333333333"
        UserRole.objects.create(user_id=uid, role=role)
        out = service.invoke("core.context", {}, user_id=uid)
        assert "enabled_modules" in out


def test_audit_tool_requires_permission(synced, db_tenant):
    from easybiz.core.iam.models import Role, RolePermission, UserRole

    with tenant_context(db_tenant):
        role = Role.objects.create(name="r")
        RolePermission.objects.create(role=role, permission="core.audit.read")
        uid = "44444444-4444-4444-4444-444444444444"
        UserRole.objects.create(user_id=uid, role=role)
        out = service.invoke("core.audit.list", {"limit": 5}, user_id=uid)
        assert isinstance(out, list)
