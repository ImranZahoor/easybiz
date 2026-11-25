from django_tenants.utils import tenant_context

from easybiz.core.iam.models import Role, RolePermission, UserRole
from easybiz.core.kernel import lifecycle
from easybiz.core.tools import service
from easybiz.core.tools.paging_io import project


def test_project_helper():
    items = [{"a": 1, "b": 2}, {"a": 3, "b": 4}]
    assert project(items, ["a"]) == [{"a": 1}, {"a": 3}]
    assert project(items, ["a", "zzz"]) == [{"a": 1}, {"a": 3}]  # unknown key absent, no crash
    assert project(items, None) == items  # no projection


def _reader(perm):
    role = Role.objects.create(name="r")
    RolePermission.objects.create(role=role, permission=perm)
    uid = "66666666-6666-6666-6666-666666666666"
    UserRole.objects.create(user_id=uid, role=role)
    return uid


def test_projects_tool_field_limited(synced, db_tenant):
    from easybiz.modules.timesheets.models import Project

    lifecycle.enable_module(db_tenant, "timesheets")
    with tenant_context(db_tenant):
        Project.objects.create(code="ABC", name="A")
        uid = _reader("timesheets.project.read")
        out = service.invoke("timesheets.projects.list", {"fields": ["code"]}, user_id=uid)
        assert out["items"] == [{"code": "ABC"}] and "next_cursor" in out
