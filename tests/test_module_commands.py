from django.core.management import call_command

from easybiz.core.catalog.models import Module
from easybiz.core.kernel import state


def test_sync_modules_populates_catalog():
    call_command("sync_modules", verbosity=0)
    assert Module.objects.filter(id="demo").exists()


def test_tenant_module_enable_disable(db_tenant):
    call_command("sync_modules", verbosity=0)
    call_command("tenant_module", db_tenant.slug, "enable", "demo", verbosity=0)
    assert state.is_enabled(db_tenant, "demo") is True
    call_command("tenant_module", db_tenant.slug, "disable", "demo", verbosity=0)
    assert state.is_enabled(db_tenant, "demo") is False
