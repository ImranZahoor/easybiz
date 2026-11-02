from django_tenants.utils import tenant_context

from easybiz.core.events import service as events
from easybiz.core.events.models import OutboxEvent
from easybiz.core.kernel import lifecycle
from easybiz.modules.demo.models import Widget


def test_event_parked_while_disabled_then_replayed_on_enable(synced, db_tenant):
    lifecycle.enable_module(db_tenant, "demo")
    with tenant_context(db_tenant):
        Widget.objects.all().delete()
        ev = OutboxEvent.objects.create(
            name="core.module.enabled", producer="core", payload={"module": "x"}
        )
    lifecycle.disable_module(db_tenant, "demo")  # demo handler's module now disabled
    with tenant_context(db_tenant):
        counts = events.dispatch_pending()
        assert counts["parked"] >= 1
        ev.refresh_from_db()
        assert "demo" in ev.parked and ev.status == OutboxEvent.PENDING
        assert Widget.objects.count() == 0  # handler did not run
    lifecycle.enable_module(db_tenant, "demo")  # enable_module calls requeue_parked("demo")
    with tenant_context(db_tenant):
        events.dispatch_pending()
        assert Widget.objects.filter(name="x").count() == 1  # replayed exactly once
