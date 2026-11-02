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


def test_parked_event_not_re_dispatched_until_requeue(synced, db_tenant):
    lifecycle.enable_module(db_tenant, "demo")
    lifecycle.disable_module(db_tenant, "demo")
    with tenant_context(db_tenant):
        ev = OutboxEvent.objects.create(
            name="core.module.enabled", producer="core", payload={"module": "x"}
        )
        now = ev.next_attempt_at
        assert events.dispatch_pending(now=now)["parked"] >= 1
        # a second sweep at the same instant must not re-pick the parked event
        assert events.dispatch_pending(now=now)["parked"] == 0


def test_requeue_parked_leaves_dead_events_dead(synced, db_tenant):
    with tenant_context(db_tenant):
        ev = OutboxEvent.objects.create(
            name="core.module.enabled",
            producer="core",
            payload={},
            status=OutboxEvent.DEAD,
            parked=["demo"],
        )
        events.requeue_parked("demo")
        ev.refresh_from_db()
        assert ev.status == OutboxEvent.DEAD  # a dead event is never resurrected
