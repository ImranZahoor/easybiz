import pytest
from django_tenants.utils import tenant_context

from easybiz.core.iam import service as iam
from easybiz.core.iam.enums import PolicyEffect
from easybiz.core.iam.policy import PolicyError

PERM = "timesheets.entry.approve"
GT = {"op": "gt", "left": {"var": "resource.hours"}, "right": {"var": "subject.approval_limit"}}


def _enable_timesheets(tenant):
    from easybiz.core.kernel import lifecycle

    lifecycle.enable_module(tenant, "timesheets", actor_id=None)


def test_create_rejects_invalid_condition(synced, db_tenant):
    with tenant_context(db_tenant):
        _enable_timesheets(db_tenant)
        with pytest.raises(PolicyError):
            iam.create_policy(
                db_tenant,
                permission=PERM,
                effect=PolicyEffect.DENY_IF,
                condition={"op": "regex", "left": {"var": "resource.x"}, "right": "a"},
                actor_id=None,
            )


def test_create_rejects_unknown_permission(synced, db_tenant):
    with tenant_context(db_tenant):
        with pytest.raises(PolicyError):
            iam.create_policy(
                db_tenant,
                permission="made.up.perm",
                effect=PolicyEffect.DENY_IF,
                condition=GT,
                actor_id=None,
            )


def test_evaluate_dry_run_reports_decider(synced, db_tenant):
    with tenant_context(db_tenant):
        _enable_timesheets(db_tenant)
        p = iam.create_policy(
            db_tenant, permission=PERM, effect=PolicyEffect.DENY_IF, condition=GT, priority=5, actor_id=None
        )
        hit = iam.evaluate_policy(
            db_tenant, permission=PERM, subject={"approval_limit": 8}, resource={"hours": 10}, context={}
        )
        assert hit["allowed"] is False and hit["decided_by"] == str(p.id)
        miss = iam.evaluate_policy(
            db_tenant, permission=PERM, subject={"approval_limit": 8}, resource={"hours": 6}, context={}
        )
        assert miss["allowed"] is True


def test_priority_orders_decider(synced, db_tenant):
    with tenant_context(db_tenant):
        _enable_timesheets(db_tenant)
        iam.create_policy(db_tenant, permission=PERM, effect=PolicyEffect.DENY_IF, condition=GT, priority=1, actor_id=None)
        hi = iam.create_policy(db_tenant, permission=PERM, effect=PolicyEffect.DENY_IF, condition=GT, priority=9, actor_id=None)
        res = iam.evaluate_policy(
            db_tenant, permission=PERM, subject={"approval_limit": 8}, resource={"hours": 10}, context={}
        )
        assert res["decided_by"] == str(hi.id)


def test_policy_change_invalidates_authorize(synced, db_tenant):
    with tenant_context(db_tenant):
        _enable_timesheets(db_tenant)
        from easybiz.core.iam.models import Role, RolePermission, UserAttribute, UserRole

        role = Role.objects.create(name="r")
        RolePermission.objects.create(role=role, permission=PERM)
        uid = "33333333-3333-3333-3333-333333333333"
        UserRole.objects.create(user_id=uid, role=role)
        UserAttribute.objects.create(user_id=uid, key="approval_limit", value=8)
        assert iam.authorize(uid, PERM, resource={"hours": 10}) is True  # warms the (empty) policy cache
        iam.create_policy(db_tenant, permission=PERM, effect=PolicyEffect.DENY_IF, condition=GT, actor_id=None)
        assert iam.authorize(uid, PERM, resource={"hours": 10}) is False  # bump took effect


def test_user_attribute_crud(synced, db_tenant):
    with tenant_context(db_tenant):
        uid = "44444444-4444-4444-4444-444444444444"
        iam.set_user_attribute(uid, "approval_limit", 8, actor_id=None)
        assert iam.user_attributes(uid) == {"approval_limit": 8}
        iam.set_user_attribute(uid, "approval_limit", 12, actor_id=None)
        assert iam.user_attributes(uid) == {"approval_limit": 12}
        iam.remove_user_attribute(uid, "approval_limit", actor_id=None)
        assert iam.user_attributes(uid) == {}


def test_create_policy_writes_audit(synced, db_tenant):
    with tenant_context(db_tenant):
        _enable_timesheets(db_tenant)
        from easybiz.core.audit.models import AuditLog

        iam.create_policy(db_tenant, permission=PERM, effect=PolicyEffect.DENY_IF, condition=GT, actor_id=None)
        assert AuditLog.objects.filter(action="policy.created").exists()
