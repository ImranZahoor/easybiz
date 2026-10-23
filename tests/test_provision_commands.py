from django.core.management import call_command

from easybiz.core.kernel import state
from easybiz.core.tenancy.models import Tenant


def test_provision_tenant_command(synced, request):
    def _cleanup():
        from django.db import connection

        connection.set_schema_to_public()
        with connection.cursor() as cur:
            cur.execute('DROP SCHEMA IF EXISTS "t_cli" CASCADE')
        Tenant.objects.filter(slug="cli").delete()

    request.addfinalizer(_cleanup)
    call_command(
        "provision_tenant",
        "cli",
        "--domain",
        "cli.localhost",
        "--owner-email",
        "owner@cli.test",
        "--owner-password",
        "change-me-now",
        "--modules",
        "demo",
        verbosity=0,
    )
    tenant = Tenant.objects.get(slug="cli")
    assert state.is_enabled(tenant, "demo") is True


def test_upgrade_modules_command(synced, provision):
    from easybiz.core.catalog.models import TenantModule

    tenant = provision(slug="upg", modules=("demo",))
    call_command("upgrade_modules", verbosity=0)
    row = TenantModule.objects.get(tenant=tenant, module_id="demo")
    assert row.installed_version == "0.1.0"
