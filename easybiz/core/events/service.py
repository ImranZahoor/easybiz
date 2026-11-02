from __future__ import annotations

from collections import Counter
from datetime import timedelta

from django.conf import settings
from django.db import connection, transaction
from django.utils import timezone

from easybiz.core.events.models import InboxProcessed, OutboxEvent
from easybiz.core.kernel import state
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
    live = OutboxEvent.objects.filter(parked__contains=module_id, status=OutboxEvent.PENDING)
    for event in live:
        event.parked = [m for m in event.parked if m != module_id]
        event.status = OutboxEvent.PENDING
        event.next_attempt_at = timezone.now()
        event.save(update_fields=["parked", "status", "next_attempt_at"])
        count += 1
    return count


def dispatch_pending(limit: int = 100, now=None) -> Counter:
    """Deliver due pending events in the current tenant schema, idempotently."""
    now = now or timezone.now()
    counts: Counter = Counter()
    with transaction.atomic():
        due = list(
            OutboxEvent.objects.select_for_update(skip_locked=True)
            .filter(status=OutboxEvent.PENDING, next_attempt_at__lte=now)
            .order_by("created_at")[:limit]
        )
        for event in due:
            failed = parked = False
            for func in registry.handlers_for(event.name):
                module_id, key = _handler_key(func)
                if module_id is None:
                    continue
                if InboxProcessed.objects.filter(event_id=event.id, handler=key).exists():
                    continue
                if module_id != "core" and not _module_enabled(module_id):
                    if module_id not in event.parked:
                        event.parked = [*event.parked, module_id]
                    parked = True
                    counts["parked"] += 1
                    continue
                if _run_handler(func, event, key):
                    counts["delivered"] += 1
                else:
                    failed = True
            _finalise(event, failed=failed, parked=parked, now=now, counts=counts)
    return counts


def _handler_key(func) -> tuple[str | None, str]:
    """A handler's owning module id and inbox key ``<module_id>.<func-name>``."""
    module_id = registry.module_id_for(func.__module__)
    return module_id, f"{module_id}.{func.__name__}"


def _module_enabled(module_id: str) -> bool:
    """Whether a module is enabled for the schema the dispatcher is running in."""
    # connection.tenant is set by django-tenants' schema switch (monkeypatched).
    return state.is_enabled(connection.tenant, module_id)  # type: ignore[attr-defined]


def _run_handler(func, event, key: str) -> bool:
    """Run one handler in a savepoint; record the inbox row on success."""
    try:
        with transaction.atomic():
            func(_event_dict(event))
            InboxProcessed.objects.create(event_id=event.id, handler=key)
        return True
    except Exception as exc:  # noqa: BLE001 - recorded on the event and retried
        event.last_error = str(exc)
        return False


def _event_dict(event) -> dict:
    """The payload view handed to a handler (§5.2 handler signature)."""
    return {"id": event.id, "name": event.name, "payload": event.payload, "version": event.version}


def _finalise(event, *, failed: bool, parked: bool, now, counts: Counter) -> None:
    """Advance an event's status after its handlers ran: retry, dead, park, or done."""
    if failed:
        event.attempts += 1
        if event.attempts >= settings.EASYBIZ_EVENT_MAX_ATTEMPTS:
            event.status = OutboxEvent.DEAD
            counts["dead"] += 1
        else:
            event.next_attempt_at = now + timedelta(seconds=min(5 * 2**event.attempts, 3600))
            counts["retry"] += 1
        event.save()
    elif parked:
        # Stays pending; replayed by requeue_parked when the module is enabled. Push the
        # next attempt out so parked events do not hot-loop and starve deliverable ones.
        event.next_attempt_at = now + timedelta(hours=1)
        event.save()
    else:
        event.status = OutboxEvent.DONE
        event.processed_at = now
        counts["events_done"] += 1
        event.save()
