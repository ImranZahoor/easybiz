# F21b — Error Envelope (additive, on `/api/`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every error response — on both ninja planes and the two kernel middlewares — a single predictable envelope `{"detail", "code", "errors", "request_id"}`, additively (keep `detail`, remove nothing, no `/api/v1`), with a request id set and returned on every response.

**Architecture:** A shared `easybiz/core/api/envelope.py` builds the envelope dict from `(detail, status, code?, request_id?, errors?)` with a status→code default map. `DomainError` gains an optional `code`. A new `RequestIDMiddleware` runs first, stamping `request.request_id` (from an incoming `X-Request-ID` or a fresh `uuid4().hex`) and setting the `X-Request-ID` response header on every response. The ninja exception handlers (tenant `api` + `platform_api`) and the two kernel middlewares (`TenantStatus`, `ModuleGate`) all route their bodies through `envelope.build`; a ninja `ValidationError` handler turns request-body validation into `errors: [{field, code, message}]`.

**Tech Stack:** Python 3.13, Django 6.1, django-ninja/pydantic, django-tenants, `uv`/pytest on real PostgreSQL. No new dependencies.

**Spec:** `ERP-CORE-SPEC.md` §21 F21 item 1 (error envelope — "Keep `detail`; add `code`, `errors`, `request_id`"), Appendix E (error code catalogue), and §F19 item 1 ("Middleware sets and returns `X-Request-ID`"; "the id is returned in the response header and in error bodies").

## Global Constraints

- No new dependencies. Imports at top of file; no module-level docstrings and single-line function docstrings (match the house style of `easybiz/core/api/*.py`).
- **Additive only:** the envelope keeps `detail` unchanged and only adds keys; no endpoint path changes; no `/api/v1`. (Spec §21.2: additive changes do not require a new version.)
- The `errors` key is always present — `[]` except on a 422 field-validation failure.
- Codes come from Appendix E verbatim: `auth.forbidden` (403), `resource.not_found` (404), `resource.conflict` (409), `resource.version_mismatch` (412), `resource.precondition_required` (428), `rate.limited` (429), `validation.failed` (422), `auth.token_invalid` (401), `module.not_enabled` (404 module gate), `tenant.suspended` (403 suspended tenant).
- Tests run on real PostgreSQL (`uv run pytest`); no SQLite, no mocks.

## Non-goals (deferred F21 slices)

`Idempotency-Key`/`idem_key`, optimistic concurrency (`version`/`ETag`/`If-Match`), `count` in the pagination envelope, OpenAPI hygiene + CI diff, the `/api/v1` migration, and finer auth-401 codes (`auth.token_expired`/`auth.mfa_required`, which arrive with the F13 auth-deepening slice). Unhandled server exceptions (500) remain Django's default response — the envelope covers *handled* errors only.

## Review Focus

- **422 field errors** — a request-body validation failure returns `errors: [{field, code, message}]` (not ninja's raw `loc`/`msg`/`type` list), with top-level `code = "validation.failed"`, so the frontend can show inline messages. (Task 1.)
- **401 envelope** — an unauthenticated request to an authed endpoint returns the envelope (`code = "auth.token_invalid"`), not ninja's bare `{"detail": "Unauthorized"}`. (Task 1.)
- **Request id on success too** — the `X-Request-ID` header is present on a 200, and an incoming `X-Request-ID` is echoed back. (Task 2.)
- **Middleware-origin errors match** — `module.not_enabled` (404) and `tenant.suspended` (403), which bypass ninja, carry the same `{detail, code, errors, request_id}` shape with their Appendix E codes. (Task 2.)
- **Hostile incoming request id** — a malformed/oversized client `X-Request-ID` is not reflected verbatim into the header and body (log-forging / header-injection guard); it is replaced by a fresh id. (Task 2.)

---

### Task 1: The envelope + ninja exception handlers

**Files:**
- Create: `easybiz/core/api/envelope.py`
- Modify: `easybiz/core/errors.py` (add `code` to `DomainError`)
- Modify: `easybiz/core/api/__init__.py` (route the `DomainError` handler through the envelope; add `ValidationError` + `AuthenticationError` handlers)
- Modify: `easybiz/core/platform_api/__init__.py` (route all five handlers through the envelope; add `ValidationError` + `AuthenticationError`)
- Test: `tests/test_error_envelope.py`

**Interfaces:**
- Consumes: `ninja.errors.ValidationError` (has `.errors`: a list of `{"loc": [...], "msg": str, "type": str}`), `ninja.errors.AuthenticationError`; `NinjaAPI.create_response(request, data, status=...)`.
- Produces:
  - `envelope.DEFAULT_CODES: dict[int, str]` — the status→code map from Global Constraints (401/403/404/409/412/422/428/429).
  - `envelope.build(detail: str, status: int, *, code: str | None = None, request_id: str | None = None, errors: list | None = None) -> dict` — returns `{"detail": detail, "code": code or DEFAULT_CODES.get(status, "error"), "errors": errors or [], "request_id": request_id}`.
  - `envelope.field_errors(exc) -> list[dict]` — maps a ninja `ValidationError` to `[{"field": str(e["loc"][-1]), "code": e.get("type", "invalid"), "message": e.get("msg", "")} for e in exc.errors]`.
  - `DomainError.code: str | None` — new optional 3rd constructor arg `code=None`, stored as `self.code`; existing subclasses that call `super().__init__(message, status)` keep `code=None` and fall back to the status default.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_error_envelope.py
from django.test import Client

from easybiz.core.api import envelope
from easybiz.core.errors import DomainError


def test_build_shape_and_default_code():
    out = envelope.build("nope", 403, request_id="rid1")
    assert out == {"detail": "nope", "code": "auth.forbidden", "errors": [], "request_id": "rid1"}


def test_build_explicit_code_and_errors():
    out = envelope.build("bad", 422, code="validation.failed",
                         errors=[{"field": "hours", "code": "range", "message": "too big"}])
    assert out["code"] == "validation.failed" and out["errors"][0]["field"] == "hours"


def test_domain_error_carries_optional_code():
    assert DomainError("x", 404).code is None            # falls back to status default at build
    assert DomainError("x", 404, "module.not_enabled").code == "module.not_enabled"


def _login_owner(provision, slug):
    provision(slug=slug, modules=())
    return Client().post("/api/auth/login",
                         data={"email": f"owner@{slug}.test", "password": "change-me-now"},
                         content_type="application/json", HTTP_HOST=f"{slug}.localhost")


def test_401_is_enveloped(synced, provision):
    provision(slug="e1", modules=())
    r = Client().get("/api/tools", HTTP_HOST="e1.localhost")  # authed endpoint, no credentials
    assert r.status_code == 401
    body = r.json()
    assert body["code"] == "auth.token_invalid" and body["errors"] == [] and "request_id" in body


def test_422_body_validation_has_field_errors(synced, provision):
    provision(slug="e2", modules=())
    r = Client().post("/api/auth/login", data={}, content_type="application/json",
                      HTTP_HOST="e2.localhost")  # missing email/password → ninja ValidationError
    assert r.status_code == 422
    body = r.json()
    assert body["code"] == "validation.failed"
    assert body["errors"] and all({"field", "code", "message"} <= set(e) for e in body["errors"])


def test_domain_error_conflict_is_enveloped(synced, provision):
    # a DomainError (RoleError, 409) must flow through the DomainError handler into the envelope.
    # Use the role-create endpoint (see tests/test_core_roles_write_api.py for the exact path/body);
    # create the same role name twice — the second returns 409 with the default 409 code.
    token = _login_owner(provision, "e3").json()["access_token"]
    hdr = {"HTTP_HOST": "e3.localhost", "HTTP_AUTHORIZATION": f"Bearer {token}"}
    body = {"name": "dup-role", "permissions": []}  # adjust to the real create-role schema
    Client().post("/api/core/roles", data=body, content_type="application/json", **hdr)
    r = Client().post("/api/core/roles", data=body, content_type="application/json", **hdr)
    assert r.status_code == 409
    assert r.json()["code"] == "resource.conflict" and r.json()["errors"] == []
```

> Note for the implementer: `tests/test_core_roles_write_api.py` has the exact create-role path and request schema — mirror it for `test_domain_error_conflict_is_enveloped`. If role-create isn't the cleanest 409 on this branch, any existing tenant endpoint that raises a `DomainError` 409 works; the assertion is the envelope shape + default code, not the endpoint.

- [ ] **Step 2: Run them, verify they fail** — Run: `uv run pytest tests/test_error_envelope.py -q` — Expected: FAIL (`envelope` module missing; handlers return bare `{"detail"}`).

- [ ] **Step 3: Implement**
  - `envelope.py`: `DEFAULT_CODES`, `build`, `field_errors` per Interfaces.
  - `errors.py`: `def __init__(self, message, status, code=None)` → `self.status = status; self.code = code`.
  - `api/__init__.py`: rewrite `_on_domain_error` to `return api.create_response(request, envelope.build(str(exc), exc.status, code=exc.code, request_id=getattr(request, "request_id", None)), status=exc.status)`. Add `@api.exception_handler(ValidationError)` → status 422, `code="validation.failed"`, `errors=envelope.field_errors(exc)`. Add `@api.exception_handler(AuthenticationError)` → status 401 (code defaults to `auth.token_invalid`).
  - `platform_api/__init__.py`: route all existing handlers (`TenantConflict`→409 `resource.conflict`, `LifecycleError`→409 `resource.conflict`, `TenantValidationError`→422 `validation.failed`, `WeakPassword`→422 `validation.failed`, `DomainError`→`exc.status`/`exc.code`) through `envelope.build`; add the same `ValidationError` and `AuthenticationError` handlers.
  - `request_id` is read with `getattr(request, "request_id", None)` everywhere (it is `None` until Task 2 wires the middleware — the key is still present).

- [ ] **Step 4: Run them, verify they pass** — Run: `uv run pytest tests/test_error_envelope.py -q` — Expected: PASS.

- [ ] **Step 5: Run the API suites for regressions** — Run: `uv run pytest tests/test_auth_api.py tests/test_tools_api.py tests/test_core_roles_api.py tests/test_platform_auth_api.py -q` — Expected: PASS (envelope is additive; `detail` still present).

- [ ] **Step 6: Commit** — `git add -A && git commit -m "Add error envelope (code/errors/request_id) to ninja exception handlers"`

---

### Task 2: RequestIDMiddleware + the kernel middlewares

**Files:**
- Create: `easybiz/core/api/middleware.py` (`RequestIDMiddleware`)
- Modify: `config/settings.py` (register `RequestIDMiddleware` first in `MIDDLEWARE`)
- Modify: `easybiz/core/kernel/middleware.py` (`TenantStatusMiddleware`, `ModuleGateMiddleware` → envelope bodies)
- Test: `tests/test_request_id.py`

**Interfaces:**
- Consumes: `envelope.build` (Task 1); `uuid.uuid4`.
- Produces:
  - `RequestIDMiddleware` — standard Django middleware (`__init__(self, get_response)` / `__call__(self, request)`). On the way in: `request.request_id = _clean(request.headers.get("X-Request-ID")) or uuid4().hex`. On the way out: `response["X-Request-ID"] = request.request_id`; return `response`.
  - `RequestIDMiddleware._clean(raw) -> str | None` — accept the client id only if it is a non-empty str, ≤ 64 chars, and matches `^[A-Za-z0-9._-]+$`; otherwise return `None` (mint a fresh id). Prevents header-injection / log-forging from a hostile client id.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_request_id.py
from django.test import Client


def test_request_id_header_on_success(synced, provision):
    provision(slug="r1", modules=())
    r = Client().post("/api/auth/login",
                      data={"email": "owner@r1.test", "password": "change-me-now"},
                      content_type="application/json", HTTP_HOST="r1.localhost")
    assert r.status_code == 200 and r["X-Request-ID"]


def test_incoming_request_id_is_echoed(synced, provision):
    provision(slug="r2", modules=())
    r = Client().post("/api/auth/login",
                      data={"email": "owner@r2.test", "password": "change-me-now"},
                      content_type="application/json", HTTP_HOST="r2.localhost",
                      HTTP_X_REQUEST_ID="client-abc_123")
    assert r["X-Request-ID"] == "client-abc_123"


def test_hostile_incoming_request_id_is_replaced(synced, provision):
    provision(slug="r3", modules=())
    bad = "x" * 200 + "\r\nInjected: 1"  # oversized + CRLF injection attempt
    r = Client().post("/api/auth/login",
                      data={"email": "owner@r3.test", "password": "change-me-now"},
                      content_type="application/json", HTTP_HOST="r3.localhost",
                      HTTP_X_REQUEST_ID=bad)
    assert r["X-Request-ID"] != bad and "\n" not in r["X-Request-ID"]


def test_error_body_carries_request_id(synced, provision):
    provision(slug="r4", modules=())
    r = Client().get("/api/tools", HTTP_HOST="r4.localhost")  # 401, enveloped
    assert r.status_code == 401
    assert r.json()["request_id"] and r.json()["request_id"] == r["X-Request-ID"]


def test_module_not_enabled_is_enveloped(synced, provision):
    provision(slug="r5", modules=())  # timesheets installed but NOT enabled
    r = Client().get("/api/timesheets/projects", HTTP_HOST="r5.localhost")
    assert r.status_code == 404
    body = r.json()
    assert body["code"] == "module.not_enabled" and body["request_id"] and body["errors"] == []


def test_tenant_suspended_is_enveloped(synced, provision):
    from easybiz.core.tenancy.models import Tenant
    provision(slug="r6", modules=())
    Tenant.objects.filter(slug="r6").update(is_active=False)
    r = Client().get("/api/tools", HTTP_HOST="r6.localhost")
    assert r.status_code == 403
    assert r.json()["code"] == "tenant.suspended" and r.json()["request_id"]
```

- [ ] **Step 2: Run them, verify they fail** — Run: `uv run pytest tests/test_request_id.py -q` — Expected: FAIL (no header; middleware errors still bare `{"detail"}`).

- [ ] **Step 3: Implement**
  - `middleware.py`: `RequestIDMiddleware` + `_clean` per Interfaces.
  - `settings.py`: put `"easybiz.core.api.middleware.RequestIDMiddleware"` as the **first** entry in `MIDDLEWARE` (outermost, so it stamps `request.request_id` before the tenant/status/gate middlewares run and sets the header on every response bubbling back — including short-circuit responses from the kernel middlewares).
  - `kernel/middleware.py`: `TenantStatusMiddleware` returns `JsonResponse(envelope.build("This tenant is suspended", 403, code="tenant.suspended", request_id=getattr(request, "request_id", None)), status=403)`; `ModuleGateMiddleware` returns `JsonResponse(envelope.build(f"Module '{segment}' is not enabled for this tenant", 404, code="module.not_enabled", request_id=getattr(request, "request_id", None)), status=404)`.

- [ ] **Step 4: Run them, verify they pass** — Run: `uv run pytest tests/test_request_id.py -q` — Expected: PASS.

- [ ] **Step 5: Full suite + lint + types** — Run: `uv run pytest -q && uv run ruff check easybiz/core/api/envelope.py easybiz/core/api/middleware.py easybiz/core/kernel/middleware.py tests/test_error_envelope.py tests/test_request_id.py && uv run mypy easybiz/core/api/envelope.py easybiz/core/api/middleware.py` — Expected: all green.

- [ ] **Step 6: Commit** — `git add -A && git commit -m "Add RequestIDMiddleware and envelope the kernel middleware errors"`

---

## Post-implementation

- Update `README.md` Status with a short F21b paragraph: additive error envelope `{detail, code, errors, request_id}` on `/api/` (both planes + the two kernel middlewares); `X-Request-ID` set/echoed on every response; Appendix E codes; no `/api/v1` yet.
- No new events, no migrations.
- **Review:** standard whole-branch review, with an explicit **info-disclosure** check — the envelope reshapes auth/permission/404 error bodies, so confirm the new `code`/`detail` pairs reveal nothing more than before (e.g. no existence oracle that a 404 vs 403 didn't already expose) and that the request-id reflection is safely bounded. No authz *logic* changes, so a full security review is not required — but the reviewer must sign off on the info-disclosure question.
