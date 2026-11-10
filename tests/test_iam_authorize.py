from django_tenants.utils import tenant_context

from easybiz.core.iam import service as iam
from easybiz.core.iam.enums import PolicyEffect
from easybiz.core.iam.models import Policy, Role, RolePermission, UserAttribute, UserRole

PERM = "timesheets.entry.approve"
GT = {"op": "gt", "left": {"var": "resource.hours"}, "right": {"var": "subject.approval_limit"}}


def _user_with(perms):
    role = Role.objects.create(name="r")
    RolePermission.objects.bulk_create([RolePermission(role=role, permission=p) for p in perms])
    uid = "22222222-2222-2222-2222-222222222222"
    UserRole.objects.create(user_id=uid, role=role)
    return uid


def test_rbac_must_grant_first(synced, db_tenant):
    with tenant_context(db_tenant):
        uid = _user_with(["timesheets.entry.read"])  # lacks approve
        Policy.objects.create(
            permission=PERM,
            effect=PolicyEffect.ALLOW_IF,
            condition={"op": "eq", "left": {"var": "resource.x"}, "right": 1},
        )
        assert iam.authorize(uid, PERM, resource={"x": 1}) is False


def test_deny_if_denies(synced, db_tenant):
    with tenant_context(db_tenant):
        uid = _user_with([PERM])
        UserAttribute.objects.create(user_id=uid, key="approval_limit", value=8)
        Policy.objects.create(permission=PERM, effect=PolicyEffect.DENY_IF, condition=GT)
        assert iam.authorize(uid, PERM, resource={"hours": 10}) is False
        assert iam.authorize(uid, PERM, resource={"hours": 6}) is True


def test_allow_if_required_when_present(synced, db_tenant):
    with tenant_context(db_tenant):
        uid = _user_with([PERM])
        Policy.objects.create(
            permission=PERM,
            effect=PolicyEffect.ALLOW_IF,
            condition={"op": "eq", "left": {"var": "context.region"}, "right": "EU"},
        )
        assert iam.authorize(uid, PERM, context={"region": "US"}) is False
        assert iam.authorize(uid, PERM, context={"region": "EU"}) is True


def test_no_policies_falls_back_to_rbac(synced, db_tenant):
    with tenant_context(db_tenant):
        uid = _user_with([PERM])
        assert iam.authorize(uid, PERM, resource={"hours": 99}) is True


def test_group_pattern_policy_matches(synced, db_tenant):
    with tenant_context(db_tenant):
        uid = _user_with([PERM])
        UserAttribute.objects.create(user_id=uid, key="approval_limit", value=8)
        Policy.objects.create(permission="timesheets.*", effect=PolicyEffect.DENY_IF, condition=GT)
        assert iam.authorize(uid, PERM, resource={"hours": 10}) is False


def test_unrelated_policy_ignored(synced, db_tenant):
    with tenant_context(db_tenant):
        uid = _user_with([PERM])
        Policy.objects.create(
            permission="core.user.manage",
            effect=PolicyEffect.DENY_IF,
            condition={"op": "eq", "left": {"var": "resource.hours"}, "right": 10},
        )
        assert iam.authorize(uid, PERM, resource={"hours": 10}) is True
