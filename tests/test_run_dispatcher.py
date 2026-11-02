from django.core.management import call_command
from django_tenants.utils import tenant_context

from easybiz.core.events.models import OutboxEvent
from easybiz.modules.demo.models import Widget


def test_run_dispatcher_once_delivers_across_active_tenants(synced, provision):
    tenant = provision(slug="acme", modules=("demo",))
    with tenant_context(tenant):
        Widget.objects.all().delete()
        OutboxEvent.objects.create(
            name="core.module.enabled", producer="core", payload={"module": "x"}
        )
    call_command("run_dispatcher", "--once", verbosity=0)
    with tenant_context(tenant):
        assert Widget.objects.filter(name="x").count() == 1


def test_run_dispatcher_isolates_per_tenant_errors(synced, provision, monkeypatch):
    from django.db import connection

    from easybiz.core.kernel.management.commands import run_dispatcher as cmd

    acme = provision(slug="acme", modules=("demo",))
    beta = provision(slug="beta", modules=("demo",))
    with tenant_context(beta):
        Widget.objects.all().delete()
        OutboxEvent.objects.create(
            name="core.module.enabled", producer="core", payload={"module": "x"}
        )
    real = cmd.dispatch_pending

    def flaky(*args, **kwargs):
        if connection.schema_name == acme.schema_name:
            raise RuntimeError("boom in acme")
        return real(*args, **kwargs)

    monkeypatch.setattr(cmd, "dispatch_pending", flaky)
    call_command("run_dispatcher", "--once", verbosity=0)  # must not propagate acme's error
    with tenant_context(beta):
        assert Widget.objects.filter(name="x").count() == 1  # beta still delivered
