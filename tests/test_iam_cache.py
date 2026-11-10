from django_tenants.utils import tenant_context

from easybiz.core.iam import cache as iam_cache
from easybiz.core.iam import service as iam
from easybiz.core.iam.models import Role, RolePermission, UserRole

A = "22222222-2222-2222-2222-222222222222"
B = "33333333-3333-3333-3333-333333333333"


def test_cached_matches_and_invalidates_on_change(synced, db_tenant):
    with tenant_context(db_tenant):
        role = Role.objects.create(name="c1")
        RolePermission.objects.create(role=role, permission="core.user.read")
        UserRole.objects.create(user_id=A, role=role)

        assert iam_cache.cached_permissions_for(A) == {"core.user.read"}  # fresh + cached
        # a change through the service bumps the version -> next call recomputes
        iam.update_role(
            db_tenant,
            role.id,
            actor_id=None,
            actor_perms=None,
            changes={"permissions": ["core.user.read", "core.audit.read"]},
        )
        assert iam_cache.cached_permissions_for(A) == {"core.user.read", "core.audit.read"}


def test_users_cached_independently(synced, db_tenant):
    with tenant_context(db_tenant):
        ra = Role.objects.create(name="ra")
        RolePermission.objects.create(role=ra, permission="core.user.read")
        rb = Role.objects.create(name="rb")
        RolePermission.objects.create(role=rb, permission="core.audit.read")
        UserRole.objects.create(user_id=A, role=ra)
        UserRole.objects.create(user_id=B, role=rb)
        assert iam_cache.cached_permissions_for(A) == {"core.user.read"}
        assert iam_cache.cached_permissions_for(B) == {"core.audit.read"}
