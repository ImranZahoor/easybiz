# Easybiz M5 (Events) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the transactional outbox: `events/service.publish`, `dispatch_pending` (inbox idempotency, per-tenant module gating/parking, retry-backoff, dead-letter), `requeue_parked`, and the `run_dispatcher` command — and route the existing direct `OutboxEvent.objects.create` writes through `publish`.

**Architecture:** Events are written to `events_outboxevent` in the same transaction as the business change (already happening). M5 adds the *delivery* side: `dispatch_pending` locks due pending events (`select_for_update(skip_locked=True)`), and for each registered handler runs it in a savepoint, recording an `events_inboxprocessed` row keyed `(event_id, "<module_id>.<func>")` for at-least-once/idempotent delivery. A handler whose module is disabled for the tenant is **parked** (replayed on enable via `requeue_parked`). Failures retry with exponential backoff, then dead-letter. `run_dispatcher` sweeps active tenants. The `demo` module gains a handler so the machinery is exercised end-to-end without Timesheets (M6).

**Tech Stack:** Django 6.1 + django-tenants (`schema_context`/`tenant_context`, `select_for_update(skip_locked)`), PostgreSQL 16, pytest; `uv`.

**Spec:** `ERP-CORE-SPEC.md` — events (§5.9), models (§4.2 `OutboxEvent`/`InboxProcessed`), registry handlers/`@subscribe` (§5.2), test harness (§9), M5 (§11), invariants I6 (at-least-once, idempotent inbox), decisions D8/D11.

## Scope decision (rulings)

- M5's spec verify names `test_timesheets_and_events.py` (Timesheets = M6). M5 proves the event **machinery** against the `demo` module (it gains `handlers.py` + a `core.module.enabled` subscription), exactly as `demo` proved the module lifecycle in M3a. The canonical Timesheets event tests run in M6.
- **Resolve the M3/M4 shims:** the three direct `OutboxEvent.objects.create(...)` calls (`lifecycle.enable_module`/`disable_module`, `core_routes.delete_user`) are switched to `events.publish(...)`. `requeue_parked` **moves** from `lifecycle.py` to `events/service.py` (its spec home, §5.9); `lifecycle` imports it from there — behaviour unchanged.
- MVP delivery is a **polling dispatcher** in one transaction per sweep (D11); Celery/leases/ordering/retention are **F15**.

## Global Constraints

- Python 3.13; Django ≥5.2 (6.1); django-tenants ≥3.8; PostgreSQL 16; `uv`; pytest (DB required).
- **I6:** events published only inside the business transaction; delivery at-least-once; handlers idempotent via the inbox keyed `(event_id, handler-key)`, `handler.key = "<module_id>.<func-name>"`. **I7:** a handler of a module not enabled for the tenant does not run (parked). **I13:** resolve the tenant by `schema_name` (dispatch runs under `schema_context`, a pk-less stub).
- `publish(name, payload, producer="core", version=1)`: for `producer != "core"`, `name` must be in that module's `events.publishes`, else `EventError`.
- Backoff: `next_attempt_at = now + min(5 * 2**attempts, 3600)s`; dead at `EASYBIZ_EVENT_MAX_ATTEMPTS` (=5). `dispatch_pending` returns a `Counter(delivered, parked, retry, dead, events_done)`.
- §0.5: no module docstrings; one docstring per public class/function; imports at top; named predicates for 3+ conditions; `ruff` + `mypy easybiz config` clean; short commits, no attribution.

## Review Focus

- **Inbox idempotency (I6):** re-dispatching a delivered event never re-runs a handler (the `(event_id, key)` row blocks it); re-running with a *second* handler still delivers that one. → Task 2.
- **Parking + replay (I7):** a handler whose module is disabled parks (event stays `pending`, module id recorded in `parked`); `requeue_parked`/enable replays it and it then delivers exactly once (inbox still holds). → Task 3.
- **Retry/backoff/dead:** a failing handler leaves no inbox row, bumps `attempts`, sets exponential `next_attempt_at`, and dead-letters at the cap; a `dead` event is never re-picked. → Task 4.
- **Transaction boundary:** a handler failure rolls back only its savepoint (no partial inbox), not sibling handlers' successful inbox rows; the outbox row's status/attempt update persists. → Task 4.
- **Dispatcher tenant scope:** `run_dispatcher` sweeps active tenants, skips `public` and suspended tenants, and resets the connection to public afterward (I12/I13). → Task 5.

---

### Task 1: `events/service.publish` + `requeue_parked`; route shims through it

**Files:**
- Create: `easybiz/core/events/service.py`
- Modify: `easybiz/core/kernel/lifecycle.py` (import `requeue_parked` from events; switch its two `OutboxEvent.objects.create` to `publish`), `easybiz/core/api/core_routes.py` (switch `delete_user`'s create to `publish`), `easybiz/core/kernel/registry.py` (`handlers_for`)
- Test: `tests/test_events_publish.py`

**Interfaces:**
- Produces: `EventError`; `publish(name, payload=None, producer="core", version=1) -> OutboxEvent`; `requeue_parked(module_id) -> int`; `Registry.handlers_for(event_name) -> list`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_events_publish.py
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
```

- [ ] **Step 2: Run — expect fail.**

- [ ] **Step 3: Implement `events/service.py`** (publish + requeue_parked; dispatch lands in Task 2)

```python
from __future__ import annotations

from django.utils import timezone

from easybiz.core.events.models import OutboxEvent
from easybiz.core.kernel.registry import registry


class EventError(Exception):
    """Raised when a module publishes an event it did not declare."""


def publish(name: str, payload: dict | None = None, producer: str = "core", version: int = 1) -> OutboxEvent:
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
```

- [ ] **Step 4: Add `Registry.handlers_for`** (registry.py)

```python
    def handlers_for(self, event: str) -> list:
        return list(self._handlers.get(event, []))
```

- [ ] **Step 5: Route the shims through `publish` and move `requeue_parked`**

In `lifecycle.py`: delete the local `requeue_parked` function; `from easybiz.core.events.service import publish, requeue_parked`; replace the two `OutboxEvent.objects.create(name="core.module.enabled"/"core.module.disabled", ...)` with `publish("core.module.enabled", {"module": module_id, "version": manifest.version})` / `publish("core.module.disabled", {"module": module_id})`. (`enable_module` already calls `requeue_parked(module_id)` — now the imported one.) Drop the now-unused `OutboxEvent` import if unused.
In `core_routes.py` `delete_user`: replace `OutboxEvent.objects.create(name="core.membership.removed", ...)` with `events.publish("core.membership.removed", {"user_id": user_id})`; drop the `OutboxEvent` import.

- [ ] **Step 6: Run the new tests + full suite + gate; commit**

Run: `uv run pytest && uv run ruff check . && uv run mypy easybiz config`

```bash
git add easybiz/core/events/service.py easybiz/core/kernel/lifecycle.py easybiz/core/api/core_routes.py easybiz/core/kernel/registry.py tests/test_events_publish.py
git commit -m "Add events.publish and route outbox writes through it"
```

---

### Task 2: `demo` handler + `dispatch_pending` delivery & inbox idempotency

**Files:**
- Create: `easybiz/modules/demo/handlers.py`; Modify: `easybiz/modules/demo/manifest.json`
- Modify: `easybiz/core/events/service.py` (`dispatch_pending`)
- Test: `tests/test_events_dispatch.py`

**Interfaces:**
- Consumes: `registry.handlers_for`, `registry.module_id_for`, `state.is_enabled`, `connection.tenant`.
- Produces: `dispatch_pending(limit=100, now=None) -> Counter`. `demo` subscribes to `core.module.enabled` with `record_enabled` (creates a `Widget` named after the event's module).

- [ ] **Step 1: Give `demo` a handler**

`easybiz/modules/demo/manifest.json` → set `"events": {"publishes": [], "subscribes": ["core.module.enabled"]}`.
`easybiz/modules/demo/handlers.py`:

```python
from easybiz.core.kernel.registry import subscribe
from easybiz.modules.demo.models import Widget


@subscribe("core.module.enabled")
def record_enabled(event):
    """Record a widget whenever a module is enabled (demo event handler)."""
    Widget.objects.create(name=event["payload"]["module"])
```

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_events_dispatch.py
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
        OutboxEvent.objects.create(name="core.module.enabled", producer="core", payload={"module": "x"})
        counts = events.dispatch_pending()
        assert counts["delivered"] == 1
        assert Widget.objects.filter(name="x").count() == 1
        assert InboxProcessed.objects.filter(handler="demo.record_enabled").exists()


def test_inbox_blocks_reruns(synced, db_tenant):
    lifecycle.enable_module(db_tenant, "demo")
    with tenant_context(db_tenant):
        ev = OutboxEvent.objects.create(name="core.module.enabled", producer="core", payload={"module": "x"})
        events.dispatch_pending()
        count_after_first = Widget.objects.count()
        ev.refresh_from_db()
        assert ev.status == OutboxEvent.DONE
        # force a redelivery attempt: same event handler must not run again
        ev.status = OutboxEvent.PENDING
        ev.save(update_fields=["status"])
        events.dispatch_pending()
        assert Widget.objects.count() == count_after_first  # inbox blocked the rerun
```

- [ ] **Step 3: Run — expect fail** (`dispatch_pending` missing).

- [ ] **Step 4: Implement `dispatch_pending`** (append to `events/service.py`)

```python
from collections import Counter
from datetime import timedelta

from django.conf import settings
from django.db import connection, transaction

from easybiz.core.events.models import InboxProcessed
from easybiz.core.kernel import state


def _event_dict(event) -> dict:
    return {"id": event.id, "name": event.name, "payload": event.payload, "version": event.version}


def _handler_key(func) -> tuple[str | None, str]:
    module_id = registry.module_id_for(func.__module__)
    return module_id, f"{module_id}.{func.__name__}"


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
                if module_id != "core" and not state.is_enabled(connection.tenant, module_id):
                    if module_id not in event.parked:
                        event.parked = [*event.parked, module_id]
                    parked = True
                    counts["parked"] += 1
                    continue
                try:
                    with transaction.atomic():
                        func(_event_dict(event))
                        InboxProcessed.objects.create(event_id=event.id, handler=key)
                    counts["delivered"] += 1
                except Exception as exc:  # noqa: BLE001 - recorded on the event, retried
                    event.last_error = str(exc)
                    failed = True
            _finalise(event, failed=failed, parked=parked, now=now, counts=counts)
    return counts


def _finalise(event, *, failed: bool, parked: bool, now, counts: Counter) -> None:
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
        event.save()  # stays pending; replayed after requeue_parked
    else:
        event.status = OutboxEvent.DONE
        event.processed_at = now
        counts["events_done"] += 1
        event.save()
```

- [ ] **Step 5: Run the tests — expect pass; startup still loads demo.handlers**

Run: `uv run manage.py check && uv run pytest tests/test_events_dispatch.py tests/test_events_publish.py -v`
Expected: PASS; `import_module_code` now imports `demo.handlers` and its `core.module.enabled` subscription is satisfied.

- [ ] **Step 6: Full suite + gate; commit**

```bash
git add easybiz/modules/demo easybiz/core/events/service.py tests/test_events_dispatch.py
git commit -m "Add dispatch_pending delivery with inbox idempotency and demo handler"
```

---

### Task 3: Parking and replay

**Files:**
- Test: `tests/test_events_parked.py`

**Interfaces:** consumes `dispatch_pending`, `requeue_parked`, lifecycle enable/disable.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_events_parked.py
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
```

- [ ] **Step 2–3: Run (expect pass — mechanism built in Tasks 1–2); if red, fix per the failure.** Then full suite + gate.

- [ ] **Step 4: Commit**

```bash
git add tests/test_events_parked.py
git commit -m "Test event parking and replay on module enable"
```

---

### Task 4: Retry, backoff, and dead-letter

**Files:**
- Test: `tests/test_events_retry.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_events_retry.py
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
        for _ in range(settings.EASYBIZ_EVENT_MAX_ATTEMPTS):
            events.dispatch_pending(now=now)
            ev.refresh_from_db()
            now = (ev.next_attempt_at or now) + timedelta(seconds=1)
        assert ev.status == OutboxEvent.DEAD
        assert ev.attempts == settings.EASYBIZ_EVENT_MAX_ATTEMPTS
        assert not InboxProcessed.objects.filter(event_id=ev.id).exists()  # never recorded
```

- [ ] **Step 2: Run — expect pass (retry/dead built in Task 2); fix if red.** Then full suite + gate.

- [ ] **Step 3: Commit**

```bash
git add tests/test_events_retry.py
git commit -m "Test handler retry backoff and dead-lettering"
```

---

### Task 5: `run_dispatcher` command

**Files:**
- Create: `easybiz/core/kernel/management/commands/run_dispatcher.py`
- Test: `tests/test_run_dispatcher.py`

**Interfaces:**
- Produces: `run_dispatcher [--once] [--interval 2]` — sweeps active tenants (excluding `public`, pausing suspended) in `schema_context`, calling `dispatch_pending`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_run_dispatcher.py
from django.core.management import call_command
from django_tenants.utils import tenant_context

from easybiz.core.events.models import OutboxEvent
from easybiz.core.kernel import lifecycle
from easybiz.modules.demo.models import Widget


def test_run_dispatcher_once_delivers_across_active_tenants(synced, provision):
    tenant = provision(slug="acme", modules=("demo",))
    with tenant_context(tenant):
        Widget.objects.all().delete()
        OutboxEvent.objects.create(name="core.module.enabled", producer="core", payload={"module": "x"})
    call_command("run_dispatcher", "--once", verbosity=0)
    with tenant_context(tenant):
        assert Widget.objects.filter(name="x").count() == 1
```

- [ ] **Step 2: Run — expect fail.**

- [ ] **Step 3: Implement `run_dispatcher.py`**

```python
import time

from django.core.management.base import BaseCommand
from django_tenants.utils import get_public_schema_name, schema_context

from easybiz.core.events.service import dispatch_pending
from easybiz.core.tenancy.models import Tenant


class Command(BaseCommand):
    """Deliver outbox events for every active tenant (polling; Celery is F15)."""

    def add_arguments(self, parser) -> None:
        parser.add_argument("--once", action="store_true")
        parser.add_argument("--interval", type=int, default=2)

    def handle(self, *args, **options) -> None:
        public = get_public_schema_name()
        while True:
            for schema in (
                Tenant.objects.filter(is_active=True)
                .exclude(schema_name=public)
                .values_list("schema_name", flat=True)
            ):
                with schema_context(schema):
                    dispatch_pending()
            if options["once"]:
                break
            time.sleep(options["interval"])
```

- [ ] **Step 4: Run — expect pass; full suite + gate.** (Test uses `--once`; the sleep loop is not exercised.)

- [ ] **Step 5: Commit**

```bash
git add easybiz/core/kernel/management/commands/run_dispatcher.py tests/test_run_dispatcher.py
git commit -m "Add run_dispatcher command"
```

---

### Task 6: README + milestone close

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update README** — Status: **M5 complete** (events). `events.publish` writes the outbox in-transaction; `dispatch_pending` delivers to registered handlers with inbox idempotency, per-tenant parking + replay, retry/backoff, and dead-lettering; `run_dispatcher` sweeps active tenants. The M3/M4 direct `OutboxEvent` writes now go through `publish`. Add `uv run manage.py run_dispatcher` (and `--once`) to the command list. Next: **M6** (the real Timesheets module + its event/capability tests).

- [ ] **Step 2: Full gate**

Run: `uv run pytest && uv run ruff check . && uv run ruff format --check . && uv run mypy easybiz config && uv run manage.py makemigrations --check --dry-run`
Expected: all green; `No changes detected` (M5 adds no models).

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "Document M5 events in README"
```

---

## M5 Definition of Done

- [ ] `events.publish` writes an `OutboxEvent` in the current schema/transaction; a module publishing an undeclared event raises `EventError`; lifecycle/core_routes route through `publish`; `requeue_parked` lives in `events/service.py`.
- [ ] `dispatch_pending` delivers to each registered handler once (inbox keyed `(event_id, "<module>.<func>")`); re-dispatch never re-runs a delivered handler.
- [ ] A handler whose module is disabled parks (event stays `pending`, module id in `parked`); enabling the module replays it and it delivers exactly once.
- [ ] A failing handler leaves no inbox row, increments `attempts`, backs off (`min(5*2**attempts, 3600)s`), and dead-letters at `EASYBIZ_EVENT_MAX_ATTEMPTS`; `dead`/other-tenant events aren't re-picked.
- [ ] `run_dispatcher --once` sweeps active tenants, skips `public` and suspended, and leaves the connection on public.
- [ ] `uv run pytest` green on real PostgreSQL; `ruff` + `mypy easybiz config` clean; `makemigrations --check` clean; README updated; commits short, no attribution.
