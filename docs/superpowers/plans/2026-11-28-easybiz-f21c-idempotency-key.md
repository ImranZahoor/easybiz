# F21c — Idempotency-Key Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a client make a `POST` on the tenant `/api/` plane safely retryable — sending the same `Idempotency-Key` replays the stored response instead of running the operation twice — so an interrupted or retried agent/client write never duplicates work.

**Architecture:** A per-tenant `idem_key` table (new app `easybiz.core.idempotency`) records each in-flight/completed keyed request. A pure `service.py` holds the state machine — `request_hash` (which folds the caller's credential in, so a different caller with the same key can never replay someone else's response), `claim` (insert-or-reclaim over the unique key, the concurrency guard), and `finalize` (store a 2xx response or release the key). A thin `IdempotencyMiddleware` (after the tenant/module middlewares, so the schema is resolved) wraps `POST`s that carry the header: replay, 409, 422, or run-and-store. Everything else passes through untouched.

**Tech Stack:** Python 3.13, Django 6.1, django-tenants, django-ninja, PostgreSQL 16, `uv`/pytest on real PostgreSQL. No new dependencies.

**Spec:** `ERP-CORE-SPEC.md` §21 F21 item 4 (Idempotency — "`Idempotency-Key` header on creating and action `POST`s; tenant table `idem_key` (`key`, `endpoint`, `request_hash`, `status`, `body`, `expires_at`); same key and payload replays the stored response; same key with a different payload returns 422") and Appendix E (`idempotency.payload_mismatch` → 422; `resource.conflict` → 409). Acceptance: "Idempotent replay, payload mismatch, concurrent duplicate requests (one execution) are tested."

## Global Constraints

- No new dependencies. Imports at top; no module-level docstrings; single-line function docstrings (house style of `easybiz/core/**`).
- `idem_key` is a **per-tenant** table → the app goes in `TENANT_APPS`; the public/platform schema has no such table and is never touched by this feature.
- Idempotency is **client-driven and opt-in by the client**: it engages only when an `Idempotency-Key` header is present on a `POST`; absent header, non-`POST`, or public schema → unchanged passthrough.
- Only **2xx** responses are cached; any non-2xx releases the key so a retry re-executes.
- Error bodies reuse `easybiz/core/api/envelope.build` (Appendix E codes): `resource.conflict` (409), `idempotency.payload_mismatch` (422).
- Tests on real PostgreSQL (`uv run pytest`); the new migration must be committed (CI runs `makemigrations --check`).

## Non-goals (deferred)

Periodic cleanup of expired rows (a job, needs F11 — expired rows are simply ignored and reclaimed on next use); idempotency for `PUT`/`PATCH`/`DELETE`; the `/api/v1` move; streaming-response caching (a streaming 2xx releases the key rather than caching an unreadable body).

## Review Focus

- **Cross-caller replay leak** — the same key sent by a *different* caller (different `Authorization`) must NOT replay the first caller's stored response; it returns 422 `idempotency.payload_mismatch`. (Task 1: `request_hash` folds the credential in; Task 2 integration.)
- **Concurrent duplicate → one execution** — a second request arriving while the first is `in_progress` gets 409 `resource.conflict`, not a second execution. (Task 1: `claim` returns `CONFLICT` for an `in_progress` row; Task 2: pre-seeded `in_progress` row → 409.)
- **Error is not cached** — a handler returning non-2xx releases the key; the same key retried re-executes. (Task 1: `finalize` deletes on non-2xx; Task 2 integration.)
- **Expired key reclaimed** — a row past `expires_at` is treated as absent; the request runs fresh. (Task 1: `claim` reclaims an expired row.)
- **Passthrough paths** — absent header, a non-`POST`, or the public/platform schema create no row and alter nothing. (Task 2 middleware.)

---

### Task 1: The `idem_key` table + the claim/finalize state machine

**Files:**
- Create: `easybiz/core/idempotency/__init__.py`, `easybiz/core/idempotency/apps.py`, `easybiz/core/idempotency/models.py`, `easybiz/core/idempotency/service.py`
- Create (generated): `easybiz/core/idempotency/migrations/0001_initial.py`
- Modify: `config/settings.py` (add `"easybiz.core.idempotency"` to `TENANT_APPS`)
- Test: `tests/test_idempotency_service.py`

**Interfaces:**
- Produces:
  - `models.IdemKey` — fields: `key` (`CharField(max_length=200, unique=True)`), `endpoint` (`CharField(max_length=200)`), `request_hash` (`CharField(max_length=64)`), `status` (`CharField(max_length=12)`, `"in_progress"`/`"completed"`), `response_status` (`IntegerField(null=True)`), `body` (`TextField(default="")`), `created_at` (`DateTimeField(auto_now_add=True)`), `expires_at` (`DateTimeField`).
  - `apps.IdempotencyConfig` — `name = "easybiz.core.idempotency"`, `label = "idempotency"`, `default_auto_field = "django.db.models.BigAutoField"` (mirror `easybiz/core/audit/apps.py`).
  - `service.TTL: timedelta = timedelta(hours=24)`.
  - `service.FRESH`, `service.REPLAY`, `service.CONFLICT`, `service.MISMATCH` — string constants naming the four outcomes.
  - `service.Claim` — a dataclass `(kind: str, response_status: int | None = None, body: str = "")`.
  - `service.request_hash(method: str, path: str, body: bytes, auth_header: str) -> str` — `sha256` hex over `method`, `path`, `auth_header`, and `body` joined by `"\n"` (the credential is part of the hash → a different caller ⇒ different hash).
  - `service.claim(key: str, endpoint: str, request_hash: str) -> Claim` — in one `transaction.atomic()`: attempt `IdemKey.objects.create(...)` inside a nested `atomic()` savepoint; on `IntegrityError` the savepoint rolls back and the outer transaction stays usable, then `select_for_update().get(key=key)` and decide: expired (`expires_at <= now`) → reclaim the row (reset to `in_progress`, new hash/endpoint/expiry, clear `response_status`/`body`, save) → `FRESH`; `request_hash` differs → `MISMATCH`; `status == "completed"` → `REPLAY(response_status, body)`; else → `CONFLICT`. A successful create → `FRESH`.
  - `service.finalize(key: str, response_status: int, body: str) -> None` — if `200 <= response_status < 300`: set the row (`status="completed"`, `response_status`, `body`); else delete the row (release the key).
  - Use `django.utils.timezone.now()` for the clock.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_idempotency_service.py
from datetime import timedelta

from django.utils import timezone
from django_tenants.utils import tenant_context

from easybiz.core.idempotency import service
from easybiz.core.idempotency.models import IdemKey


def _hash(body=b"{}", auth="Bearer a"):
    return service.request_hash("POST", "/api/core/roles", body, auth)


def test_first_claim_is_fresh(synced, db_tenant):
    with tenant_context(db_tenant):
        assert service.claim("k1", "/api/core/roles", _hash()).kind == service.FRESH
        assert IdemKey.objects.get(key="k1").status == "in_progress"


def test_second_claim_while_in_progress_is_conflict(synced, db_tenant):
    with tenant_context(db_tenant):
        h = _hash()
        service.claim("k2", "/api/core/roles", h)
        assert service.claim("k2", "/api/core/roles", h).kind == service.CONFLICT


def test_completed_same_hash_replays(synced, db_tenant):
    with tenant_context(db_tenant):
        h = _hash()
        service.claim("k3", "/api/core/roles", h)
        service.finalize("k3", 201, '{"id": "x"}')
        c = service.claim("k3", "/api/core/roles", h)
        assert c.kind == service.REPLAY and c.response_status == 201 and c.body == '{"id": "x"}'


def test_different_caller_same_key_is_mismatch(synced, db_tenant):
    with tenant_context(db_tenant):
        service.claim("k4", "/api/core/roles", _hash(auth="Bearer alice"))
        service.finalize("k4", 201, '{"id": "a"}')
        # bob reuses alice's key → different auth → different hash → mismatch, never a replay
        c = service.claim("k4", "/api/core/roles", _hash(auth="Bearer bob"))
        assert c.kind == service.MISMATCH


def test_non_2xx_releases_the_key(synced, db_tenant):
    with tenant_context(db_tenant):
        h = _hash()
        service.claim("k5", "/api/core/roles", h)
        service.finalize("k5", 422, '{"detail": "no"}')
        assert not IdemKey.objects.filter(key="k5").exists()
        assert service.claim("k5", "/api/core/roles", h).kind == service.FRESH  # reusable


def test_expired_row_is_reclaimed(synced, db_tenant):
    with tenant_context(db_tenant):
        h = _hash()
        service.claim("k6", "/api/core/roles", h)
        IdemKey.objects.filter(key="k6").update(expires_at=timezone.now() - timedelta(minutes=1))
        assert service.claim("k6", "/api/core/roles", h).kind == service.FRESH  # expired ⇒ fresh
```

- [ ] **Step 2: Create the app skeleton + model, then generate the migration** — write `__init__.py`, `apps.py`, `models.py`; add the app to `TENANT_APPS`; run `uv run python manage.py makemigrations idempotency` and confirm `0001_initial.py` is created.

- [ ] **Step 3: Run the tests, verify they fail** — Run: `uv run pytest tests/test_idempotency_service.py -q` — Expected: FAIL (`service` functions undefined).

- [ ] **Step 4: Implement `service.py`** per Interfaces (the nested-`atomic()` savepoint around `create()` is the one non-obvious piece — it keeps the outer transaction usable after the `IntegrityError` so the `select_for_update` can run).

- [ ] **Step 5: Run the tests, verify they pass** — Run: `uv run pytest tests/test_idempotency_service.py -q` — Expected: PASS.

- [ ] **Step 6: Commit** — `git add -A && git commit -m "Add idem_key table and the idempotency claim/finalize state machine"`

---

### Task 2: `IdempotencyMiddleware` on the tenant plane

**Files:**
- Create: `easybiz/core/idempotency/middleware.py`
- Modify: `config/settings.py` (register the middleware after `ModuleGateMiddleware`)
- Test: `tests/test_idempotency_api.py`

**Interfaces:**
- Consumes: `service.claim`/`finalize`/`request_hash` and the `FRESH`/`REPLAY`/`CONFLICT`/`MISMATCH` constants (Task 1); `easybiz.core.api.envelope.build`; `django.db.connection` + `django_tenants.utils.get_public_schema_name`; `django.http.HttpResponse`/`JsonResponse`.
- Produces: `IdempotencyMiddleware` — standard Django middleware. In `__call__`:
  - Passthrough (return `self.get_response(request)` unchanged) when `request.method != "POST"`, the `Idempotency-Key` header is absent, or `connection.schema_name == get_public_schema_name()`.
  - Else compute `h = service.request_hash(request.method, request.get_full_path(), request.body, request.headers.get("Authorization", ""))` and `c = service.claim(key, request.get_full_path(), h)`:
    - `REPLAY` → `resp = HttpResponse(c.body, status=c.response_status, content_type="application/json")`; `resp["Idempotency-Replayed"] = "true"`; return it.
    - `CONFLICT` → `JsonResponse(envelope.build("a request with this Idempotency-Key is already in progress", 409, code="resource.conflict", request_id=getattr(request, "request_id", None)), status=409)`.
    - `MISMATCH` → `JsonResponse(envelope.build("Idempotency-Key was already used with a different request", 422, code="idempotency.payload_mismatch", request_id=getattr(request, "request_id", None)), status=422)`.
    - `FRESH` → `response = self.get_response(request)`; then `service.finalize(key, response.status_code, response.content.decode() if not response.streaming else "")` (a streaming response releases the key); return `response`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_idempotency_api.py
import json

from django.test import Client
from django_tenants.utils import tenant_context


def _owner(provision, slug):
    provision(slug=slug, modules=())
    return Client().post(
        "/api/auth/login",
        data={"email": f"owner@{slug}.test", "password": "change-me-now"},
        content_type="application/json", HTTP_HOST=f"{slug}.localhost",
    ).json()["access_token"]


def _create_role(token, slug, name, key=None):
    kw = {"HTTP_HOST": f"{slug}.localhost", "HTTP_AUTHORIZATION": f"Bearer {token}",
          "content_type": "application/json"}
    if key is not None:
        kw["HTTP_IDEMPOTENCY_KEY"] = key
    return Client().post("/api/core/roles",
                         data=json.dumps({"name": name, "description": "", "permissions": []}), **kw)


def test_replay_returns_stored_response(synced, provision):
    token = _owner(provision, "i1")
    first = _create_role(token, "i1", "role-a", key="key-1")
    assert first.status_code == 201
    again = _create_role(token, "i1", "role-a", key="key-1")  # same key, same payload
    assert again.status_code == 201
    assert again.json() == first.json() and again["Idempotency-Replayed"] == "true"
    from easybiz.core.iam.models import Role
    from easybiz.core.tenancy.models import Tenant
    with tenant_context(Tenant.objects.get(slug="i1")):
        assert Role.objects.filter(name="role-a").count() == 1  # created once


def test_same_key_different_payload_is_422(synced, provision):
    token = _owner(provision, "i2")
    _create_role(token, "i2", "role-x", key="key-2")
    r = _create_role(token, "i2", "role-y", key="key-2")  # same key, different body
    assert r.status_code == 422 and r.json()["code"] == "idempotency.payload_mismatch"


def test_in_progress_key_conflicts(synced, provision):
    from easybiz.core.idempotency.models import IdemKey
    from easybiz.core.tenancy.models import Tenant
    token = _owner(provision, "i3")
    with tenant_context(Tenant.objects.get(slug="i3")):
        from django.utils import timezone
        from datetime import timedelta
        from easybiz.core.idempotency import service
        h = service.request_hash("POST", "/api/core/roles", b"", f"Bearer {token}")
        IdemKey.objects.create(key="key-3", endpoint="/api/core/roles", request_hash=h,
                               status="in_progress", expires_at=timezone.now() + timedelta(hours=1))
    r = _create_role(token, "i3", "role-z", key="key-3")  # a duplicate is mid-flight
    assert r.status_code == 409 and r.json()["code"] == "resource.conflict"


def test_error_response_is_not_cached(synced, provision):
    token = _owner(provision, "i4")
    _create_role(token, "i4", "dup", key="key-4")          # first create succeeds (201)
    bad = _create_role(token, "i4", "dup", key="key-5")    # duplicate name → 422 under a NEW key
    assert bad.status_code == 422
    from easybiz.core.idempotency.models import IdemKey
    from easybiz.core.tenancy.models import Tenant
    with tenant_context(Tenant.objects.get(slug="i4")):
        assert not IdemKey.objects.filter(key="key-5").exists()  # released, reusable


def test_no_header_passes_through(synced, provision):
    token = _owner(provision, "i5")
    r = _create_role(token, "i5", "plain")  # no Idempotency-Key
    assert r.status_code == 201
    from easybiz.core.idempotency.models import IdemKey
    from easybiz.core.tenancy.models import Tenant
    with tenant_context(Tenant.objects.get(slug="i5")):
        assert IdemKey.objects.count() == 0  # nothing recorded
```

- [ ] **Step 2: Run them, verify they fail** — Run: `uv run pytest tests/test_idempotency_api.py -q` — Expected: FAIL (middleware not registered; no replay/409/422 behavior).

- [ ] **Step 3: Implement the middleware and register it** — write `middleware.py`; in `config/settings.py` insert `"easybiz.core.idempotency.middleware.IdempotencyMiddleware"` immediately **after** `"easybiz.core.kernel.middleware.ModuleGateMiddleware"` (schema + module gate resolved first; `request.request_id` already set by the first-in-chain `RequestIDMiddleware`).

- [ ] **Step 4: Run them, verify they pass** — Run: `uv run pytest tests/test_idempotency_api.py -q` — Expected: PASS.

- [ ] **Step 5: Full suite + lint + types + migration check** — Run: `uv run pytest -q && uv run ruff check easybiz/core/idempotency && uv run mypy easybiz/core/idempotency && uv run python manage.py makemigrations --check` — Expected: all green, no missing migrations.

- [ ] **Step 6: Commit** — `git add -A && git commit -m "Add IdempotencyMiddleware: replay/409/422 for keyed POSTs on the tenant plane"`

---

## Post-implementation

- Update `README.md` Status with a short F21c paragraph: client-driven `Idempotency-Key` on tenant `POST`s; `idem_key` table; replay / 409 in-progress / 422 payload-mismatch; caller folded into the hash (no cross-caller replay); 2xx-only caching; cleanup job + `PUT`/`PATCH` deferred.
- No new events. One migration (`idempotency.0001_initial`).
- **Reviews:** a standard whole-branch review **and** a security review (per the standing instruction — this caches and replays response bodies on an authenticated write path). The security review must confirm: the caller-folded hash actually prevents one caller replaying another's stored response within a tenant; no cross-tenant reach (the table is per-schema); the concurrency guard yields exactly one execution; and a cached body cannot leak data the retrying caller wouldn't otherwise be authorized to see.
