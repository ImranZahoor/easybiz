import pytest
from django.core.management import CommandError, call_command

from easybiz.core.catalog.models import Module, Permission, TenantModule
from easybiz.core.kernel import lifecycle


def _throwaway_module(mid):
    m = Module.objects.create(id=mid, name=mid.title(), version="0.1.0", manifest={})
    Permission.objects.create(code=f"{mid}.thing.read", module=m, description="x")
    return m


def test_uninstall_removes_catalog_and_permissions(synced):
    _throwaway_module("scafrm")
    lifecycle.uninstall_module("scafrm")
    assert not Module.objects.filter(id="scafrm").exists()
    assert not Permission.objects.filter(module_id="scafrm").exists()


def test_uninstall_refuses_while_tenant_has_row(synced, db_tenant):
    m = _throwaway_module("scafref")
    TenantModule.objects.create(
        tenant=db_tenant, module=m, status=TenantModule.ENABLED, installed_version="0.1.0"
    )
    with pytest.raises(lifecycle.LifecycleError):
        lifecycle.uninstall_module("scafref")
    assert Module.objects.filter(id="scafref").exists()  # untouched


def test_command_exit_code(synced):
    _throwaway_module("scafcmd")
    call_command("uninstall_module", "scafcmd")  # exits 0
    with pytest.raises(CommandError):
        call_command("uninstall_module", "nonexistent")  # not in catalog -> nonzero
