import uuid

from django_tenants.utils import tenant_context

from easybiz.core.iam import service as iam
from easybiz.core.iam.models import Role, RolePermission, UserRole


def test_has_permission_wildcards():
    assert iam.has_permission({"*"}, "core.module.read")
    assert iam.has_permission({"core.module.read"}, "core.module.read")
    assert iam.has_permission({"core.*"}, "core.module.read")
    assert not iam.has_permission({"other.*"}, "core.module.read")
    assert not iam.has_permission(set(), "core.module.read")


def test_permissions_for_unions_roles(synced, db_tenant):
    uid = uuid.uuid4()
    with tenant_context(db_tenant):
        r1 = Role.objects.create(name="a")
        r2 = Role.objects.create(name="b")
        RolePermission.objects.create(role=r1, permission="core.module.read")
        RolePermission.objects.create(role=r2, permission="demo.widget.read")
        UserRole.objects.create(user_id=uid, role=r1)
        UserRole.objects.create(user_id=uid, role=r2)
        assert iam.permissions_for(uid) == {"core.module.read", "demo.widget.read"}


def test_menu_for_filters_by_permission(synced, db_tenant):
    from easybiz.core.kernel import lifecycle

    lifecycle.enable_module(db_tenant, "demo")  # demo manifest menu is empty -> []
    with tenant_context(db_tenant):
        assert iam.menu_for(db_tenant, {"*"}) == []
