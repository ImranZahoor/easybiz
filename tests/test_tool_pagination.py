from django_tenants.utils import tenant_context

from easybiz.core.iam.models import Role, RolePermission, UserRole
from easybiz.core.kernel import lifecycle
from easybiz.core.tools import service


def _reader(perm):
    role = Role.objects.create(name="r")
    RolePermission.objects.create(role=role, permission=perm)
    uid = "55555555-5555-5555-5555-555555555555"
    UserRole.objects.create(user_id=uid, role=role)
    return uid


def test_projects_tool_paginates(synced, db_tenant):
    from easybiz.modules.timesheets.models import Project

    lifecycle.enable_module(db_tenant, "timesheets")
    with tenant_context(db_tenant):
        for i in range(3):
            Project.objects.create(code=f"P{i}", name=f"n{i}")
        uid = _reader("timesheets.project.read")
        p1 = service.invoke("timesheets.projects.list", {"limit": 2}, user_id=uid)
        assert len(p1["items"]) == 2 and p1["next_cursor"]
        p2 = service.invoke(
            "timesheets.projects.list", {"limit": 2, "cursor": p1["next_cursor"]}, user_id=uid
        )
        codes = {i["code"] for i in p1["items"]} | {i["code"] for i in p2["items"]}
        assert codes == {"P0", "P1", "P2"} and p2["next_cursor"] is None


def test_audit_tool_returns_page_shape(synced, db_tenant):
    with tenant_context(db_tenant):
        uid = _reader("core.audit.read")
        out = service.invoke("core.audit.list", {"limit": 5}, user_id=uid)
        assert set(out) == {"items", "next_cursor"} and isinstance(out["items"], list)
