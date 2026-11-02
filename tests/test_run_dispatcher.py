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
