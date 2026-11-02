import pytest
from django_tenants.utils import tenant_context

from easybiz.core.iam import service as iam
from easybiz.core.iam.service import RoleError
from easybiz.core.kernel import lifecycle


def test_create_role_and_guards(synced, db_tenant):
    lifecycle.enable_module(db_tenant, "demo")
    with tenant_context(db_tenant):
        role = iam.create_role(db_tenant, "viewer", ["demo.widget.read", "core.module.read"])
        assert set(iam.role_permissions(role)) == {"demo.widget.read", "core.module.read"}
        with pytest.raises(RoleError):
            iam.create_role(db_tenant, "star", ["*"])
        with pytest.raises(RoleError):
            iam.create_role(db_tenant, "bad", ["nope.perm"])
        with pytest.raises(RoleError):
            iam.create_role(db_tenant, "viewer", ["core.module.read"])  # duplicate name


def test_assignable_excludes_disabled_module_perms(synced, db_tenant):
    with tenant_context(db_tenant):
        assignable = iam.assignable_permissions(db_tenant)
        assert "core.module.read" in assignable
        assert "demo.widget.read" not in assignable  # demo not enabled


def test_set_user_roles(synced, db_tenant):
    import uuid

    uid = uuid.uuid4()
    with tenant_context(db_tenant):
        iam.create_role(db_tenant, "r1", ["core.module.read"])
        iam.set_user_roles(uid, ["r1"])
        assert iam.permissions_for(uid) == {"core.module.read"}
        with pytest.raises(RoleError):
            iam.set_user_roles(uid, ["ghost"])
