from django_tenants.utils import tenant_context

from easybiz.core.events import service as events
from easybiz.core.events.models import InboxProcessed, OutboxEvent
from easybiz.core.kernel import lifecycle
from easybiz.modules.demo.models import Widget


def test_dispatch_delivers_to_enabled_module_handler(synced, db_tenant):
    lifecycle.enable_module(db_tenant, "demo")
    with tenant_context(db_tenant):
        events.dispatch_pending()  # drain the enable's own core.module.enabled event
        Widget.objects.all().delete()
        OutboxEvent.objects.create(
            name="core.module.enabled", producer="core", payload={"module": "x"}
        )
        counts = events.dispatch_pending()
        assert counts["delivered"] == 1
        assert Widget.objects.filter(name="x").count() == 1
        assert InboxProcessed.objects.filter(handler="demo.record_enabled").exists()


def test_inbox_blocks_reruns(synced, db_tenant):
    lifecycle.enable_module(db_tenant, "demo")
    with tenant_context(db_tenant):
        ev = OutboxEvent.objects.create(
            name="core.module.enabled", producer="core", payload={"module": "x"}
        )
        events.dispatch_pending()
        count_after_first = Widget.objects.count()
        ev.refresh_from_db()
        assert ev.status == OutboxEvent.DONE
        # force a redelivery attempt: the same event+handler must not run again
        ev.status = OutboxEvent.PENDING
        ev.save(update_fields=["status"])
        events.dispatch_pending()
        assert Widget.objects.count() == count_after_first  # inbox blocked the rerun
