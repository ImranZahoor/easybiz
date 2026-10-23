from easybiz.core.catalog.models import Module, TenantModule
from easybiz.core.kernel import state
from easybiz.core.tenancy.models import Tenant


def test_is_enabled_true_for_enabled_module(db_tenant):
    mod, _ = Module.objects.get_or_create(
        id="demo", defaults={"name": "Demo", "version": "0.1.0", "manifest": {}}
    )
    TenantModule.objects.create(
        tenant=db_tenant, module=mod, status=TenantModule.ENABLED, installed_version="0.1.0"
    )
    assert state.is_enabled(db_tenant, "demo") is True


def test_is_enabled_false_for_disabled(db_tenant):
    mod, _ = Module.objects.get_or_create(
        id="demo", defaults={"name": "Demo", "version": "0.1.0", "manifest": {}}
    )
    TenantModule.objects.create(
        tenant=db_tenant, module=mod, status=TenantModule.DISABLED, installed_version="0.1.0"
    )
    assert state.is_enabled(db_tenant, "demo") is False


def test_public_tenant_has_nothing_enabled():
    public = Tenant.objects.get(schema_name="public")
    assert state.enabled_module_ids(public) == set()
