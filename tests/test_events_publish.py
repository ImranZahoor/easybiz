import pytest
from django_tenants.utils import tenant_context

from easybiz.core.events import service as events
from easybiz.core.events.models import OutboxEvent
from easybiz.core.events.service import EventError


def test_publish_core_event(synced, db_tenant):
    with tenant_context(db_tenant):
        ev = events.publish("core.module.enabled", {"module": "demo"})
        assert ev.status == OutboxEvent.PENDING and ev.producer == "core"
        assert OutboxEvent.objects.filter(name="core.module.enabled").exists()


def test_publish_module_event_must_be_declared(synced, db_tenant):
    with tenant_context(db_tenant):
        with pytest.raises(EventError):
            events.publish("demo.not.declared", {}, producer="demo")
