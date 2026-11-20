from django_tenants.utils import tenant_context

from easybiz.core.iam.models import Role, RolePermission, UserRole
from easybiz.core.kernel import lifecycle
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
        uid = "33333333-3333-3333-3333-333333333333"
        UserRole.objects.create(user_id=uid, role=role)
        out = service.invoke(
            "timesheets.projects.create", {"code": "abc", "name": "ABC"}, user_id=uid
        )
        assert out["code"] == "ABC"
