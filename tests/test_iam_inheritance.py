from django_tenants.utils import tenant_context

from easybiz.core.iam import service as iam
from easybiz.core.iam.models import Role, RolePermission, UserRole

USER = "11111111-1111-1111-1111-111111111111"


def test_permissions_union_over_ancestors(synced, db_tenant):
    with tenant_context(db_tenant):
        base = Role.objects.create(name="base")
        RolePermission.objects.create(role=base, permission="core.audit.read")
        mid = Role.objects.create(name="mid", parent=base)
        RolePermission.objects.create(role=mid, permission="core.user.read")
        mgr = Role.objects.create(name="mgr", parent=mid)
        RolePermission.objects.create(role=mgr, permission="core.role.read")
        UserRole.objects.create(user_id=USER, role=mgr)

        perms = iam.permissions_for(USER)
        assert {"core.audit.read", "core.user.read", "core.role.read"} <= perms  # own + ancestors


def test_flat_role_unchanged(synced, db_tenant):
    with tenant_context(db_tenant):
        r = Role.objects.create(name="flat")
        RolePermission.objects.create(role=r, permission="core.user.read")
        UserRole.objects.create(user_id=USER, role=r)
        assert iam.permissions_for(USER) == {"core.user.read"}


def test_would_cycle_rejects_self_or_descendant(synced, db_tenant):
    with tenant_context(db_tenant):
        a = Role.objects.create(name="a")
        b = Role.objects.create(name="b", parent=a)
        assert iam.would_cycle(a, a) is True  # self
        assert iam.would_cycle(a, b) is True  # b descends from a -> setting a.parent=b loops
        assert iam.would_cycle(b, a) is False  # fine
