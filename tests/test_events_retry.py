from datetime import timedelta

from django.conf import settings
from django_tenants.utils import tenant_context

from easybiz.core.events import service as events
from easybiz.core.events.models import InboxProcessed, OutboxEvent
from easybiz.core.kernel import lifecycle
from easybiz.core.kernel.registry import registry


def _raising_handler(event):
    raise RuntimeError("boom")


_raising_handler.__module__ = "easybiz.modules.demo.handlers"
_raising_handler.__name__ = "record_enabled"


def test_failing_handler_retries_then_dead(synced, db_tenant, monkeypatch):
    lifecycle.enable_module(db_tenant, "demo")
    monkeypatch.setitem(registry._handlers, "core.module.enabled", [_raising_handler])
    with tenant_context(db_tenant):
        ev = OutboxEvent.objects.create(
            name="core.module.enabled", producer="core", payload={"module": "x"}
        )
        now = ev.next_attempt_at
        intervals = []
        for _ in range(settings.EASYBIZ_EVENT_MAX_ATTEMPTS):
            events.dispatch_pending(now=now)
            ev.refresh_from_db()
            if ev.status == OutboxEvent.PENDING:
                intervals.append(ev.next_attempt_at - now)
            now = ev.next_attempt_at + timedelta(seconds=1)
        assert intervals[1] > intervals[0]  # exponential backoff between retries
        assert ev.status == OutboxEvent.DEAD
        assert ev.attempts == settings.EASYBIZ_EVENT_MAX_ATTEMPTS
        assert not InboxProcessed.objects.filter(event_id=ev.id).exists()  # never recorded
