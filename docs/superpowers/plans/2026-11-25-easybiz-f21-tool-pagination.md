# F21 (pagination slice) — Cursor Pagination for the Tool Surface — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A reusable keyset (cursor) pagination helper, applied to the agent tool layer's list tools so an agent gets bounded, cursored pages (`{items, next_cursor}`) instead of unbounded arrays — serving F23e's token-budget goal, dependency-free and without `/api/v1`.

**Architecture:** `easybiz/core/api/paging.py` offers `paginate(queryset, *, limit, cursor, order_by)` — stable keyset pagination over `(order_by field, pk)` with an opaque base64 cursor; `limit` is capped at 200. The three list tools (`core.audit.list`, `timesheets.projects.list`, `timesheets.entries.list`) gain a `limit`/`cursor` input and return `{"items": [...], "next_cursor": ...}`. Tools have no stable v0 contract, so changing their output shape breaks nothing. The error envelope, idempotency, optimistic concurrency, and the `/api/v1` migration that would bring pagination to the HTTP list endpoints are later F21 slices.

**Tech Stack:** Python 3.13, Django 6.1, django-tenants, stdlib `base64`/`json`, `uv`/pytest. No new dependencies.

**Spec:** `ERP-CORE-SPEC.md` §21 (F21) item 3 (pagination/filtering) — the helper is the reusable piece the spec says modules share; this slice applies it to the tool surface (F23e). Error envelope/versioning/idempotency/concurrency/OpenAPI and filtering beyond cursor paging are deferred.

## Global Constraints

- Keyset, not offset: the cursor encodes the last row's `(order_by value, pk)`; paging is stable under inserts. `limit` defaults to 50, capped at **200**.
- The helper is reusable (core + modules) and transport-agnostic; it returns model instances + `next_cursor`, and the caller serialises.
- No change to existing HTTP list endpoints (they stay bare-array v0); only the tool handlers change (no v0 tool contract to break).
- Imports at top; no new dependencies.

## Review Focus

- **Stable keyset paging** — paging all the way through with `next_cursor` yields every row exactly once, in order, even with duplicate sort values (pk tiebreak), and `next_cursor` is `None` only on the last page. (Task 1.)
- **Limit cap** — a `limit` over 200 (or ≤0) is clamped, not honoured verbatim. (Task 1.)
- **Opaque/robust cursor** — a malformed or tampered cursor is rejected cleanly (not a 500/crash). (Task 1.)
- **Tool pagination end-to-end** — a list tool returns `{items, next_cursor}` and a second call with the cursor returns the next page (no overlap, no gap). (Task 2.)
- **Ordering preserved** — each tool keeps its natural order (audit newest-first `-at`, projects by `code`, entries newest-first `-work_date`). (Task 2.)

---

### Task 1: The pagination helper

**Files:**
- Create: `easybiz/core/api/paging.py`
- Test: `tests/test_paging.py`

**Interfaces:**
- Produces:
  - `MAX_LIMIT = 200`.
  - `class CursorError(DomainError)` — a malformed cursor (status 422).
  - `paginate(queryset, *, limit=50, cursor=None, order_by="-id") -> dict` — returns `{"items": [<model instances>], "next_cursor": str | None}`.
    - Clamp `limit` to `[1, MAX_LIMIT]`.
    - `field = order_by.lstrip("-")`, `desc = order_by.startswith("-")`; order the queryset by `(order_by, "-pk" if desc else "pk")` for a deterministic total order.
    - If `cursor`: decode `(value, pk)` (base64 of `json.dumps([value, pk])`); filter to the strict keyset successor — `desc`: `Q(**{field+"__lt": value}) | Q(**{field: value, "pk__lt": pk})`; asc: the `__gt` mirror. A decode failure raises `CursorError`.
    - Fetch `limit + 1`; if a surplus row exists, drop it and set `next_cursor = _encode(last.<field>, last.pk)`; else `next_cursor = None`.
  - `_encode(value, pk) -> str` / `_decode(cursor) -> tuple` — base64(json); `value` serialised with `isoformat()` for date/datetime else `str(value)` (Django coerces the string back in the filter for the field's type).

- [ ] **Step 1: Write the failing tests** (use a real tenant model — `AuditLog`, ordered `-at`; rows share no `at`-ties here, so also cover a tie with a crafted model or `action`)

```python
import pytest
from django_tenants.utils import tenant_context
from easybiz.core.api import paging
from easybiz.core.audit.models import AuditLog

def _rows(n):
    for i in range(n):
        AuditLog.objects.create(action=f"a{i:02d}", entity="x", entity_id=str(i))

def test_pages_through_all_rows_once(synced, db_tenant):
    with tenant_context(db_tenant):
        _rows(5)
        seen, cursor = [], None
        while True:
            page = paging.paginate(AuditLog.objects.all(), limit=2, cursor=cursor, order_by="-at")
            seen += [r.entity_id for r in page["items"]]
            cursor = page["next_cursor"]
            if cursor is None:
                break
        assert sorted(seen) == [str(i) for i in range(5)] and len(seen) == 5  # each once, no gaps

def test_limit_capped_at_200(synced, db_tenant):
    with tenant_context(db_tenant):
        _rows(201)
        page = paging.paginate(AuditLog.objects.all(), limit=10_000, order_by="-at")
        assert len(page["items"]) == 200 and page["next_cursor"] is not None  # clamped to MAX_LIMIT

def test_last_page_has_no_cursor(synced, db_tenant):
    with tenant_context(db_tenant):
        _rows(2)
        page = paging.paginate(AuditLog.objects.all(), limit=50, order_by="-at")
        assert len(page["items"]) == 2 and page["next_cursor"] is None

def test_malformed_cursor_rejected(synced, db_tenant):
    with tenant_context(db_tenant):
        with pytest.raises(paging.CursorError):
            paging.paginate(AuditLog.objects.all(), cursor="not-base64!!", order_by="-at")

def test_tie_on_sort_value_paged_by_pk(synced, db_tenant):
    with tenant_context(db_tenant):
        # same action for all rows → ties on the "action" sort; pk tiebreak must still page cleanly
        for i in range(4):
            AuditLog.objects.create(action="same", entity="x", entity_id=str(i))
        seen, cursor = [], None
        while True:
            page = paging.paginate(AuditLog.objects.all(), limit=1, cursor=cursor, order_by="action")
            seen += [r.entity_id for r in page["items"]]
            cursor = page["next_cursor"]
            if cursor is None:
                break
        assert len(set(seen)) == 4  # all four, no repeats despite identical sort values
```

- [ ] **Step 2: Run them, verify they fail** — Run: `uv run pytest tests/test_paging.py -q` — Expected: FAIL (module missing).
- [ ] **Step 3: Implement** `paging.py`.
- [ ] **Step 4: Run them, verify they pass** — Expected: PASS.
- [ ] **Step 5: Commit** — `git add easybiz/core/api/paging.py tests/test_paging.py && git commit -m "Add reusable keyset cursor pagination helper"`

---

### Task 2: Paginate the list tools

**Files:**
- Modify: `easybiz/core/tools/core_tools.py` (`core.audit.list`)
- Modify: `easybiz/modules/timesheets/tools.py` (`projects.list`, `entries.list`)
- Modify: `easybiz/modules/timesheets/queries.py` (add queryset-returning helpers reused by the list tools)
- Test: `tests/test_tool_pagination.py`

**Interfaces:**
- A shared tool input schema `PageIn(Schema)`: `limit: int = 50`, `cursor: str | None = None` (define once, e.g. in `easybiz/core/tools/paging_io.py` or reuse a `ninja.Schema` in `core_tools`).
- `core.audit.list` → `input_schema=PageIn`; handler pages `AuditLog.objects.all()` with `order_by="-at"` and returns `{"items": [<audit dict>...], "next_cursor": ...}`.
- `timesheets.projects.list` → `input_schema=PageIn`; handler pages `queries.projects_queryset()` (`Project.objects.all()`), `order_by="code"`, items `ProjectOut.of(p).model_dump()`.
- `timesheets.entries.list` → `input_schema=PageIn`; handler pages `queries.entries_queryset(user_id, can_all)`, `order_by="-work_date"`, items `EntryOut.of(e).model_dump()`.
- `queries.projects_queryset()` / `queries.entries_queryset(viewer_id, can_all)` return the querysets; refactor `all_projects`/`entries_for` to build on them (unchanged outward behaviour for their existing callers — they still return the full list).

- [ ] **Step 1: Write the failing tests**

```python
from django_tenants.utils import tenant_context
from easybiz.core.kernel import lifecycle
from easybiz.core.iam.models import Role, RolePermission, UserRole
from easybiz.core.tools import service

def _reader(perm):
    role = Role.objects.create(name="r"); RolePermission.objects.create(role=role, permission=perm)
    uid = "55555555-5555-5555-5555-555555555555"; UserRole.objects.create(user_id=uid, role=role)
    return uid

def test_projects_tool_paginates(synced, db_tenant):
    from easybiz.modules.timesheets.models import Project
    lifecycle.enable_module(db_tenant, "timesheets")
    with tenant_context(db_tenant):
        for i in range(3):
            Project.objects.create(code=f"P{i}", name=f"n{i}")
        uid = _reader("timesheets.project.read")
        p1 = service.invoke("timesheets.projects.list", {"limit": 2}, user_id=uid)
        assert len(p1["items"]) == 2 and p1["next_cursor"]
        p2 = service.invoke("timesheets.projects.list", {"limit": 2, "cursor": p1["next_cursor"]}, user_id=uid)
        codes = {i["code"] for i in p1["items"]} | {i["code"] for i in p2["items"]}
        assert codes == {"P0", "P1", "P2"} and p2["next_cursor"] is None  # all three, no overlap

def test_audit_tool_returns_page_shape(synced, db_tenant):
    with tenant_context(db_tenant):
        uid = _reader("core.audit.read")
        out = service.invoke("core.audit.list", {"limit": 5}, user_id=uid)
        assert set(out) == {"items", "next_cursor"} and isinstance(out["items"], list)
```

- [ ] **Step 2: Run them, verify they fail** — Run: `uv run pytest tests/test_tool_pagination.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement** the `PageIn` schema, the queryset helpers, and the three paginated handlers.
- [ ] **Step 4: Run them + the existing tool tests** — Run: `uv run pytest tests/test_tool_pagination.py tests/test_timesheets_tools.py tests/test_core_tools.py tests/test_module_contract.py -q` — Expected: PASS (update `test_core_tools`/`test_timesheets_tools` assertions that expected a bare list from these tools to the `{items, next_cursor}` shape).
- [ ] **Step 5: Run the full suite** — Run: `uv run pytest -q` — Expected: all pass.
- [ ] **Step 6: Commit** — `git add -A && git commit -m "Paginate the agent list tools (limit/cursor -> {items, next_cursor})"`

---

## Post-implementation
- Update `README.md` Status with a short F21-pagination paragraph (reusable keyset paginator; applied to the agent list tools; `/api/v1` + envelope + idempotency later).
- No new events; no migrations; not core authz — the standard whole-branch review applies (no security review required).
- Spec acceptance "tested on at least two modules": only `timesheets` exists as a business module today, so the reusable helper is proven on its two list tools + the core audit tool; the second module arrives with F1/F2.
- Deferred F21 (noted): error envelope + Appendix E codes; `Idempotency-Key`/`idem_key`; optimistic concurrency (version/ETag/If-Match); OpenAPI hygiene; the `/api/v1` namespace bringing pagination to HTTP list endpoints; richer filtering (`field__in`, `q`, `sort`); field-limiting/pre-summarisation for tools.
