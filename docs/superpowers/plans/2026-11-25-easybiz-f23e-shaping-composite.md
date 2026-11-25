# F23e — Agent Tooling: Response Shaping + a Composite Tool — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cut an agent's token cost two more ways — a `fields` projection that trims list-tool output to the keys the caller asks for, and a pre-aggregated composite tool (`timesheets.overview`) that replaces several round-trips with one summarised call.

**Architecture:** `PageIn` gains an optional `fields` list; the three list tools project each `items` dict to the requested keys (unknown keys simply absent; `None` = full item). A new read composite `timesheets.overview(start, end, recent)` returns `{projects, approved_hours, recent_entries}` by composing existing queries (`projects_queryset` count, `approved_hours`, `entries_queryset`) in one server-side call — pre-summed, so the model neither pages nor sums. Everything invokes through the existing F23b gate (allowlist/scope/perm/`authorize`); no new transport or authz surface.

**Tech Stack:** Python 3.13, Django 6.1, django-ninja/pydantic, `uv`/pytest. No new dependencies.

**Spec:** `ERP-CORE-SPEC.md` §F23 item 4 (low token/cost — field-limited + pre-summarised responses, composite tools) & slice 5e. Builds on F21 (paginator), F23a/b/d (registry, agent gate, module tools).

## Global Constraints

- Field projection is lenient: `fields` selects the intersection of requested-and-present keys; an unknown requested key is simply absent (no error), `fields=None`/omitted returns the full item.
- The composite tool wraps existing `queries` — no business logic re-implemented; it reads only, carries one `perm` (`timesheets.entry.read`) and `tier=read`, and is gated per tenant by module enablement like any module tool.
- Invocation unchanged: the F23b `Principal` gate (allowlist → tier/scope → key-subset → `authorize`) still applies; this slice only shapes output and adds a read tool.
- Imports at top; no new dependencies; no migrations.

## Review Focus

- **Field projection** — `fields=["code"]` on a list tool yields items with only `code`; an unknown requested key is absent (no crash); `fields` omitted returns full items. (Task 1.)
- **Projection + pagination compose** — `fields` applies to the paginated `items` without disturbing `next_cursor`. (Task 1.)
- **Composite shape** — `timesheets.overview` returns `{projects: <count>, approved_hours: <sum>, recent_entries: [...]}`, the sum matching `queries.approved_hours`. (Task 2.)
- **Composite own-vs-all** — `recent_entries` reuses `entries_queryset(user_id, can_all)`, whose own-vs-all rule is already pinned by the `entries.list` tests; the overview test covers the reader (own) path. (Task 2.)
- **Composite recent cap** — a large `recent` is clamped (bounded output). (Task 2.)

---

### Task 1: Field-limiting on the list tools

**Files:**
- Modify: `easybiz/core/tools/paging_io.py` (`PageIn.fields` + a `project` helper)
- Modify: `easybiz/core/tools/core_tools.py` (`core.audit.list`)
- Modify: `easybiz/modules/timesheets/tools.py` (`projects.list`, `entries.list`)
- Test: `tests/test_tool_field_limiting.py`

**Interfaces:**
- `PageIn` gains `fields: list[str] | None = None`.
- `paging_io.project(items: list[dict], fields: list[str] | None) -> list[dict]` — `items` unchanged if `fields` is falsy; else `[{k: v for k, v in item.items() if k in set(fields)} for item in items]`.
- Each list tool handler applies `project(items, params.fields)` to its `items` before returning `{"items": ..., "next_cursor": ...}`.

- [ ] **Step 1: Write the failing tests**

```python
from django_tenants.utils import tenant_context
from easybiz.core.iam.models import Role, RolePermission, UserRole
from easybiz.core.kernel import lifecycle
from easybiz.core.tools import service
from easybiz.core.tools.paging_io import project

def test_project_helper():
    items = [{"a": 1, "b": 2}, {"a": 3, "b": 4}]
    assert project(items, ["a"]) == [{"a": 1}, {"a": 3}]
    assert project(items, ["a", "zzz"]) == [{"a": 1}, {"a": 3}]  # unknown key absent, no crash
    assert project(items, None) == items  # no projection

def _reader(perm):
    role = Role.objects.create(name="r"); RolePermission.objects.create(role=role, permission=perm)
    uid = "66666666-6666-6666-6666-666666666666"; UserRole.objects.create(user_id=uid, role=role)
    return uid

def test_projects_tool_field_limited(synced, db_tenant):
    from easybiz.modules.timesheets.models import Project
    lifecycle.enable_module(db_tenant, "timesheets")
    with tenant_context(db_tenant):
        Project.objects.create(code="ABC", name="A")
        uid = _reader("timesheets.project.read")
        out = service.invoke("timesheets.projects.list", {"fields": ["code"]}, user_id=uid)
        assert out["items"] == [{"code": "ABC"}] and "next_cursor" in out  # only code; paging intact
```

- [ ] **Step 2: Run them, verify they fail** — Run: `uv run pytest tests/test_tool_field_limiting.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement** `PageIn.fields`, `project`, and apply it in the three handlers.
- [ ] **Step 4: Run them + the existing tool/pagination tests** — Run: `uv run pytest tests/test_tool_field_limiting.py tests/test_tool_pagination.py tests/test_core_tools.py tests/test_timesheets_tools.py -q` — Expected: PASS.
- [ ] **Step 5: Commit** — `git add -A && git commit -m "Add fields projection to the list tools (token-limited output)"`

---

### Task 2: The timesheets.overview composite tool

**Files:**
- Modify: `easybiz/modules/timesheets/tools.py` (the composite + its input schema)
- Modify: `easybiz/modules/timesheets/queries.py` (if a small helper is needed; `approved_hours`/`projects_queryset`/`entries_queryset` already exist)
- Test: `tests/test_timesheets_overview_tool.py`

**Interfaces:**
- Input `OverviewIn(Schema)`: `start: date`, `end: date`, `recent: int = 5`.
- Register `timesheets.overview` — `tier=READ`, `perm="timesheets.entry.read"`, `module_id="timesheets"`, `input_schema=OverviewIn`, `idempotent=True`. Handler:
  - `projects = queries.projects_queryset().count()`
  - `hours = queries.approved_hours(user_id, params.start, params.end)` (Decimal → `str`)
  - `can_all = iam.has_permission(iam.permissions_for(user_id), "timesheets.entry.approve")`
  - `recent = queries.entries_queryset(user_id, can_all).order_by("-work_date")[: max(1, min(params.recent, 50))]`
  - returns `{"projects": projects, "approved_hours": str(hours), "recent_entries": [{"work_date": e.work_date.isoformat(), "hours": str(e.hours), "status": e.status} for e in recent]}`.

- [ ] **Step 1: Write the failing tests**

```python
from datetime import date
from django_tenants.utils import tenant_context
from easybiz.core.iam.models import Role, RolePermission, UserRole
from easybiz.core.kernel import lifecycle
from easybiz.core.tools import service
from easybiz.core.tools.registry import registry
from easybiz.core.tools.enums import ToolTier

def test_overview_tool_registered():
    t = registry.get("timesheets.overview")
    assert t is not None and t.tier == ToolTier.READ and t.perm == "timesheets.entry.read"

def _setup(db_tenant):
    from easybiz.modules.timesheets.models import Entry, Project
    from easybiz.modules.timesheets.enums import EntryStatus
    from decimal import Decimal
    lifecycle.enable_module(db_tenant, "timesheets")
    with tenant_context(db_tenant):
        role = Role.objects.create(name="r")
        RolePermission.objects.create(role=role, permission="timesheets.entry.read")
        uid = "77777777-7777-7777-7777-777777777777"
        UserRole.objects.create(user_id=uid, role=role)
        p = Project.objects.create(code="ABC", name="A")
        Entry.objects.create(user_id=uid, project=p, work_date=date(2026, 11, 10),
                             hours=Decimal("8"), status=EntryStatus.APPROVED)
        return uid

def test_overview_pre_aggregates(synced, db_tenant):
    uid = _setup(db_tenant)
    with tenant_context(db_tenant):
        out = service.invoke("timesheets.overview",
                             {"start": "2026-11-01", "end": "2026-11-30", "recent": 5}, user_id=uid)
        assert out["projects"] == 1
        assert out["approved_hours"] == "8" and len(out["recent_entries"]) == 1

def test_overview_recent_capped(synced, db_tenant):
    uid = _setup(db_tenant)
    with tenant_context(db_tenant):
        out = service.invoke("timesheets.overview",
                             {"start": "2026-11-01", "end": "2026-11-30", "recent": 10_000}, user_id=uid)
        assert len(out["recent_entries"]) <= 50  # clamped
```

- [ ] **Step 2: Run them, verify they fail** — Run: `uv run pytest tests/test_timesheets_overview_tool.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement** `OverviewIn` + the `timesheets.overview` tool.
- [ ] **Step 4: Run them + the contract kit** — Run: `uv run pytest tests/test_timesheets_overview_tool.py tests/test_module_contract.py -q` — Expected: PASS (`check_tools` still passes: prefixed + declared perm).
- [ ] **Step 5: Run the full suite** — Run: `uv run pytest -q` — Expected: all pass.
- [ ] **Step 6: Commit** — `git add -A && git commit -m "Add timesheets.overview composite tool (pre-aggregated, one round-trip)"`

---

## Post-implementation
- Update `README.md` Status with a short F23e paragraph (field-limiting on list tools; the `timesheets.overview` composite; token-bounding completed for the agent surface).
- No new events; no migrations; not core authz — the standard whole-branch review applies.
- Note for a future slice: the composite carries a single `perm` (`timesheets.entry.read`) and exposes only a project *count* (not project details) to a caller who may lack `timesheets.project.read` — acceptable (low-sensitivity count); a multi-perm composite gate is out of scope here. Remaining F23: the MCP wire server, F23c chatbot (Anthropic SDK), `admin`-tier elevation, per-key rate limiting.
