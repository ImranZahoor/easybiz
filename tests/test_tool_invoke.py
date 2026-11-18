import pytest
from django_tenants.utils import tenant_context
from ninja import Schema

from easybiz.core.iam.models import Role, RolePermission, UserRole
from easybiz.core.tools import registry as reg
from easybiz.core.tools import service
from easybiz.core.tools.enums import ToolTier
from easybiz.core.tools.registry import Tool


class _LimitIn(Schema):
    limit: int = 10


def _reader(perms):
    role = Role.objects.create(name="r")
    RolePermission.objects.bulk_create([RolePermission(role=role, permission=p) for p in perms])
    uid = "22222222-2222-2222-2222-222222222222"
    UserRole.objects.create(user_id=uid, role=role)
    return uid


def _register(**kw):
    base = dict(
        name="t.read",
        description="d",
        tier=ToolTier.READ,
        perm="core.audit.read",
        idempotent=True,
        input_schema=None,
        handler=lambda uid, p: {"ok": True},
    )
    reg.registry.register(Tool(**{**base, **kw}))


def test_unknown_tool_404(synced, db_tenant):
    with tenant_context(db_tenant):
        with pytest.raises(service.ToolError) as e:
            service.invoke("nope", {}, user_id="00000000-0000-0000-0000-000000000000")
        assert e.value.status == 404


def test_missing_permission_403(synced, db_tenant):
    with tenant_context(db_tenant):
        _register()
        uid = _reader(["core.user.read"])  # lacks core.audit.read
        with pytest.raises(service.ToolError) as e:
            service.invoke("t.read", {}, user_id=uid)
        assert e.value.status == 403


def test_write_tool_refused(synced, db_tenant):
    with tenant_context(db_tenant):
        _register(name="t.write", tier=ToolTier.WRITE, perm=None)
        uid = _reader([])
        with pytest.raises(service.ToolError) as e:
            service.invoke("t.write", {}, user_id=uid)
        assert e.value.status == 403


def test_invalid_input_422(synced, db_tenant):
    with tenant_context(db_tenant):
        _register(name="t.in", perm=None, input_schema=_LimitIn)
        uid = _reader([])
        with pytest.raises(service.ToolError) as e:
            service.invoke("t.in", {"limit": "not-an-int"}, user_id=uid)
        assert e.value.status == 422


def test_happy_path_invokes_and_audits(synced, db_tenant):
    from easybiz.core.audit.models import AuditLog

    with tenant_context(db_tenant):
        _register()
        uid = _reader(["core.audit.read"])
        assert service.invoke("t.read", {}, user_id=uid) == {"ok": True}
        assert AuditLog.objects.filter(action="tool.invoked", entity_id="t.read").exists()


def test_non_dict_input_422(synced, db_tenant):
    with tenant_context(db_tenant):
        _register(name="t.in", perm=None, input_schema=_LimitIn)
        uid = _reader([])
        with pytest.raises(service.ToolError) as e:
            service.invoke("t.in", [1, 2], user_id=uid)
        assert e.value.status == 422


def test_extra_input_key_422(synced, db_tenant):
    with tenant_context(db_tenant):
        _register(name="t.in2", perm=None, input_schema=_LimitIn)
        uid = _reader([])
        with pytest.raises(service.ToolError) as e:
            service.invoke("t.in2", {"limit": 5, "evil": 1}, user_id=uid)
        assert e.value.status == 422


def test_no_input_tool_rejects_inputs_422(synced, db_tenant):
    with tenant_context(db_tenant):
        _register(name="t.none", perm=None, input_schema=None)
        uid = _reader([])
        with pytest.raises(service.ToolError) as e:
            service.invoke("t.none", {"evil": 1}, user_id=uid)
        assert e.value.status == 422


def test_accessible_filters_by_permission(synced, db_tenant):
    with tenant_context(db_tenant):
        _register()  # perm core.audit.read
        _register(name="t.open", perm=None)
        uid = _reader([])  # no perms
        names = {t.name for t in service.accessible(uid)}
        assert "t.open" in names and "t.read" not in names
