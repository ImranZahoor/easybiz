from __future__ import annotations

from django.utils import timezone

from easybiz.core.events.models import OutboxEvent
from easybiz.core.kernel.registry import registry


class EventError(Exception):
    """Raised when a module publishes an event it did not declare."""


def publish(
    name: str, payload: dict | None = None, producer: str = "core", version: int = 1
) -> OutboxEvent:
    """Write an outbox event in the current schema and transaction."""
    if producer != "core":
        manifest = registry.manifest(producer)
        if manifest is None or name not in manifest.publishes:
            raise EventError(f"module {producer!r} does not declare event {name!r}")
    return OutboxEvent.objects.create(
        name=name, producer=producer, payload=payload or {}, version=version
    )


def requeue_parked(module_id: str) -> int:
    """Re-queue events parked on a module after it is enabled (the inbox blocks re-runs)."""
    count = 0
    for event in OutboxEvent.objects.filter(parked__contains=module_id):
        event.parked = [m for m in event.parked if m != module_id]
        event.status = OutboxEvent.PENDING
        event.next_attempt_at = timezone.now()
        event.save(update_fields=["parked", "status", "next_attempt_at"])
        count += 1
    return count
