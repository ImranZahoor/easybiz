import pytest
from django.db import connection
from django_tenants.utils import get_public_schema_name, tenant_context

from easybiz.core.catalog.models import Permission, TenantModule
from easybiz.core.iam.models import Role
from easybiz.core.kernel import lifecycle, state


def test_sync_catalog_installs_demo_permission(synced):
    assert Permission.objects.filter(code="demo.widget.read").exists()


def test_enable_creates_tables_and_roles_in_that_tenant_only(synced, db_tenant, tables_in):
    lifecycle.enable_module(db_tenant, "demo")
    assert "demo_widget" in tables_in(db_tenant.schema_name)
    assert state.is_enabled(db_tenant, "demo") is True
    with tenant_context(db_tenant):
        assert Role.objects.filter(name="demo_viewer").exists()
    assert connection.schema_name == get_public_schema_name()  # restored (I12)


def test_enable_twice_raises(synced, db_tenant):
    lifecycle.enable_module(db_tenant, "demo")
    with pytest.raises(lifecycle.LifecycleError):
        lifecycle.enable_module(db_tenant, "demo")


def test_enable_unknown_module_raises(synced, db_tenant):
    with pytest.raises(lifecycle.LifecycleError):
        lifecycle.enable_module(db_tenant, "nope")


def test_disable_keeps_tables_then_reenable(synced, db_tenant, tables_in):
    lifecycle.enable_module(db_tenant, "demo")
    lifecycle.disable_module(db_tenant, "demo")
    assert state.is_enabled(db_tenant, "demo") is False
    assert "demo_widget" in tables_in(db_tenant.schema_name)
    lifecycle.enable_module(db_tenant, "demo")
    assert state.is_enabled(db_tenant, "demo") is True


def test_remove_requires_disable_then_drops_tables(synced, db_tenant, tables_in):
    lifecycle.enable_module(db_tenant, "demo")
    with pytest.raises(lifecycle.LifecycleError):
        lifecycle.remove_module_data(db_tenant, "demo")  # still enabled
    lifecycle.disable_module(db_tenant, "demo")
    lifecycle.remove_module_data(db_tenant, "demo")
    assert "demo_widget" not in tables_in(db_tenant.schema_name)
    assert not TenantModule.objects.filter(tenant=db_tenant, module_id="demo").exists()
