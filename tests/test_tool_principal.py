import pytest
from django_tenants.utils import tenant_context

from easybiz.core.iam.enums import PolicyEffect
from easybiz.core.iam.models import Policy, Role, RolePermission, UserRole
from easybiz.core.tools import registry as reg
from easybiz.core.tools import service
from easybiz.core.tools.enums import ToolTier
from easybiz.core.tools.registry import Tool

USER = "22222222-2222-2222-2222-222222222222"


def _user_with(perms):
    role = Role.objects.create(name="r")
    RolePermission.objects.bulk_create([RolePermission(role=role, permission=p) for p in perms])
    UserRole.objects.create(user_id=USER, role=role)


def _reg(name, tier=ToolTier.READ, perm="core.audit.read"):
    reg.registry.register(
        Tool(
            name=name,
            description="d",
            tier=tier,
            perm=perm,
            idempotent=True,
            input_schema=None,
            handler=lambda u, p: {"ok": name},
        )
    )


def _agent(scope="read", allowlist=("core.read",), key_perms=("core.audit.read",)):
    return service.Principal(
        subject_user_id=USER,
        scope=scope,
        allowlist=set(allowlist),
        actor_id="99999999-9999-9999-9999-999999999999",
        on_behalf_of=USER,
        key_perms=set(key_perms),
    )


def test_allowlist_denies(synced, db_tenant):
    with tenant_context(db_tenant):
        _user_with(["core.audit.read"])
        _reg("core.read")
        with pytest.raises(service.ToolError) as e:
            service._invoke("core.read", {}, _agent(allowlist=["other"]))
        assert e.value.status == 403


def test_read_scope_denies_write_tool(synced, db_tenant):
    with tenant_context(db_tenant):
        _user_with(["core.audit.read"])
        _reg("core.write", tier=ToolTier.WRITE)
        with pytest.raises(service.ToolError) as e:
            service._invoke("core.write", {}, _agent(allowlist=["core.write"]))
        assert e.value.status == 403


def test_intersection_user_lacks(synced, db_tenant):
    with tenant_context(db_tenant):
        _user_with([])  # user holds nothing
        _reg("core.read")
        with pytest.raises(service.ToolError):  # key allows it but authorize(user) denies
            service._invoke("core.read", {}, _agent())


def test_intersection_key_excludes(synced, db_tenant):
    with tenant_context(db_tenant):
        _user_with(["core.audit.read"])
        _reg("core.read")
        with pytest.raises(service.ToolError):  # user has it but the key's subset doesn't
            service._invoke("core.read", {}, _agent(key_perms=["core.user.read"]))


def test_agent_invokes_when_both_grant_and_audits(synced, db_tenant):
    from easybiz.core.audit.models import AuditLog

    with tenant_context(db_tenant):
        _user_with(["core.audit.read"])
        _reg("core.read")
        assert service._invoke("core.read", {}, _agent())["ok"] == "core.read"
        assert AuditLog.objects.filter(action="tool.invoked", entity_id="core.read").exists()


def test_abac_deny_blocks_agent(synced, db_tenant):
    with tenant_context(db_tenant):
        _user_with(["core.audit.read"])
        _reg("core.read")
        Policy.objects.create(
            permission="core.audit.read",
            effect=PolicyEffect.DENY_IF,
            condition={"op": "eq", "left": 1, "right": 1},  # always-true deny
        )
        with pytest.raises(service.ToolError):
            service._invoke("core.read", {}, _agent())
