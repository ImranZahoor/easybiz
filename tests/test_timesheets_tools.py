import pytest
from django_tenants.utils import tenant_context

from easybiz.core.iam.models import Role, RolePermission, UserRole
from easybiz.core.kernel import lifecycle
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
        uid = "33333333-3333-3333-3333-333333333333"
        UserRole.objects.create(user_id=uid, role=role)
        assert isinstance(service.invoke("timesheets.projects.list", {}, user_id=uid), list)


def test_timesheets_tool_gated_when_disabled(synced, db_tenant):
    with tenant_context(db_tenant):
        role = Role.objects.create(name="r")
        RolePermission.objects.create(role=role, permission="timesheets.project.read")
        uid = "44444444-4444-4444-4444-444444444444"
        UserRole.objects.create(user_id=uid, role=role)
        with pytest.raises(service.ToolError) as e:
            service.invoke("timesheets.projects.list", {}, user_id=uid)  # timesheets not enabled
        assert e.value.status == 404
