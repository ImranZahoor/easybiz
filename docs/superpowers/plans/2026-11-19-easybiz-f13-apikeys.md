# F13 (API keys slice) — Service Credentials — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tenant-scoped API keys as service credentials — issued once (prefix + hashed secret), permissions a subset of the creator's, revocable and expirable, authenticated in constant time, audited as a service principal — the credential primitive the F23b agent/MCP path will build on.

**Architecture:** A tenant `iam_apikey` row stores a public `prefix` and the SHA-256 `secret_hash` (never the secret). `iam.service` generates `<prefix>.<secret>` (shown once), enforces that the requested permissions are a subset of the creator's effective permissions (reusing `_assert_grantable`), and `authenticate_api_key(raw)` resolves + constant-time-compares + checks revocation/expiry + stamps `last_used_at`. `/api/core/apikeys` (JWT-authed, `core.apikey.manage`) manages them. Applying keys as a request auth method on a transport — with on-behalf-of-user, a tool allowlist, a read/write scope, and per-key rate limiting — is **F23b** (this slice ships the credential + `authenticate_api_key`, not the transport wiring).

**Tech Stack:** Python 3.13, Django 6.1, django-tenants, stdlib `hashlib`/`hmac`/`secrets`, `uv`/pytest. No new dependencies.

**Spec:** `ERP-CORE-SPEC.md` §F13 item 6 (API keys) + its acceptance criterion. Other F13 parts (refresh, reset, invitations, MFA, SSO, signing keys, brute-force, password policy) are separate slices; reset/invitations/MFA-policy/SSO depend on unbuilt F9/F5.

## Global Constraints

- The secret is a 256-bit random value shown **once**; only its SHA-256 hash is stored; comparison is **constant-time** (`hmac.compare_digest`); the plaintext is never stored or logged.
- A key's permissions must be a **subset of the creator's** effective permissions (reuse `iam._assert_grantable(perms, creator_perms)`; `*`/None = unrestricted).
- Identity tables stay in `public` only for global identity; API keys are **tenant-scoped** and live in the tenant `iam` app (like roles) — a key belongs to one tenant's schema.
- A key is a service principal: audit records for key management use the acting user; F23b will record key-authenticated calls with `actor = key id` flagged service.
- Domain errors subclass `DomainError`; imports at top; new permission `core.apikey.manage`.
- Deferred to F23b (noted, not built here): applying `ApiKeyAuth` to a transport, per-key rate limiting, on-behalf-of-user, tool allowlist, read/write scope.

## Review Focus

- **Subset escalation** — creating a key with a permission the creator lacks is rejected (no privilege escalation via a key). (Task 2.)
- **Secret handling** — the plaintext secret is returned only on create, never stored/returned afterward; `authenticate` compares in constant time and never logs the secret. (Task 2.)
- **Revocation/expiry** — a revoked or expired key does not authenticate. (Task 2.)
- **Malformed credential** — a missing-dot / unknown-prefix / wrong-secret value returns `None`, not a crash. (Task 2.)
- **Management authorization** — `/api/core/apikeys` requires `core.apikey.manage`; a key lists without its secret. (Task 3.)

---

### Task 1: ApiKey model

**Files:**
- Modify: `easybiz/core/iam/models.py`
- Create: `easybiz/core/iam/migrations/0004_apikey.py`
- Test: `tests/test_apikey_model.py`

**Interfaces:**
- Produces `iam.models.ApiKey`: `id` UUID pk; `name` CharField(100); `prefix` CharField(16, unique, db_index); `secret_hash` CharField(64); `permissions` `models.JSONField(default=list)`; `created_by` UUIDField (the issuing user, by value — I2); `created_at` auto_now_add; `expires_at` DateTimeField(null=True, blank=True); `last_used_at` DateTimeField(null=True, blank=True); `revoked_at` DateTimeField(null=True, blank=True).

- [ ] **Step 1: Write the failing test**

```python
from django_tenants.utils import tenant_context
from easybiz.core.iam.models import ApiKey

def test_apikey_row(synced, db_tenant):
    with tenant_context(db_tenant):
        k = ApiKey.objects.create(name="ci", prefix="abcd1234", secret_hash="x" * 64,
                                  permissions=["core.audit.read"], created_by="11111111-1111-1111-1111-111111111111")
        assert k.revoked_at is None and k.expires_at is None and k.permissions == ["core.audit.read"]
```

- [ ] **Step 2: Run it, verify it fails** — Run: `uv run pytest tests/test_apikey_model.py -q` — Expected: FAIL (model missing).
- [ ] **Step 3: Add the model and `makemigrations iam`** (confirm it writes `0004_apikey.py`).
- [ ] **Step 4: Run it + the migration check** — Run: `uv run pytest tests/test_apikey_model.py -q && uv run manage.py makemigrations --check --dry-run` — Expected: PASS + "No changes detected".
- [ ] **Step 5: Commit** — `git add easybiz/core/iam/models.py easybiz/core/iam/migrations/0004_apikey.py tests/test_apikey_model.py && git commit -m "Add iam_apikey model"`

---

### Task 2: API key service (issue, authenticate, revoke)

**Files:**
- Modify: `easybiz/core/iam/service.py`
- Test: `tests/test_apikey_service.py`

**Interfaces:**
- Consumes: `_assert_grantable`, `has_permission`, `audit.record`, stdlib `secrets`/`hashlib`/`hmac`, `django.utils.timezone`.
- Produces:
  - `class ApiKeyError(DomainError)` — `__init__(message)` → status 422.
  - `_hash_secret(secret: str) -> str` — `hashlib.sha256(secret.encode()).hexdigest()`.
  - `create_api_key(name, permissions, *, creator_id, creator_perms, expires_at=None) -> tuple[ApiKey, str]` — validates the permission subset with the same rule as `_assert_grantable` but raising **`ApiKeyError`** on violation (wrap the `_assert_grantable` call and re-raise its `RoleError` as `ApiKeyError`, or inline the check), generates `prefix = secrets.token_hex(8)` (retry on the rare collision) and `secret = secrets.token_urlsafe(32)`, stores `secret_hash=_hash_secret(secret)`, audits `apikey.created`, returns `(key, f"{prefix}.{secret}")` — the only time the secret exists.
  - `authenticate_api_key(raw: str) -> ApiKey | None` — split on the first `.`; look up by `prefix`; `hmac.compare_digest(stored_hash, _hash_secret(secret))`; reject if `revoked_at` set or `expires_at` passed; on success set `last_used_at` and return the key; any failure → `None` (never raises).
  - `list_api_keys() -> list[ApiKey]`; `revoke_api_key(key_id, *, actor_id) -> None` (idempotent set `revoked_at`; audit `apikey.revoked`).

- [ ] **Step 1: Write the failing tests**

```python
import pytest
from datetime import timedelta
from django.utils import timezone
from django_tenants.utils import tenant_context
from easybiz.core.iam import service as iam
from easybiz.core.iam.models import ApiKey

CREATOR = "11111111-1111-1111-1111-111111111111"

def test_create_returns_secret_once_and_hashes(synced, db_tenant):
    with tenant_context(db_tenant):
        key, secret = iam.create_api_key("ci", ["core.audit.read"], creator_id=CREATOR,
                                         creator_perms={"core.audit.read"})
        assert secret.startswith(key.prefix + ".")
        assert key.secret_hash != secret and len(key.secret_hash) == 64  # hashed, not plaintext
        assert iam.authenticate_api_key(secret).id == key.id

def test_subset_rule_blocks_escalation(synced, db_tenant):
    with tenant_context(db_tenant):
        with pytest.raises(iam.ApiKeyError):
            iam.create_api_key("ci", ["core.user.manage"], creator_id=CREATOR,
                               creator_perms={"core.audit.read"})  # creator lacks it

def test_revoked_key_does_not_authenticate(synced, db_tenant):
    with tenant_context(db_tenant):
        key, secret = iam.create_api_key("ci", [], creator_id=CREATOR, creator_perms=None)
        iam.revoke_api_key(key.id, actor_id=CREATOR)
        assert iam.authenticate_api_key(secret) is None

def test_expired_key_does_not_authenticate(synced, db_tenant):
    with tenant_context(db_tenant):
        key, secret = iam.create_api_key("ci", [], creator_id=CREATOR, creator_perms=None,
                                         expires_at=timezone.now() - timedelta(seconds=1))
        assert iam.authenticate_api_key(secret) is None

def test_malformed_and_wrong_secret_return_none(synced, db_tenant):
    with tenant_context(db_tenant):
        key, secret = iam.create_api_key("ci", [], creator_id=CREATOR, creator_perms=None)
        assert iam.authenticate_api_key("no-dot") is None
        assert iam.authenticate_api_key("unknownprefix.whatever") is None
        assert iam.authenticate_api_key(f"{key.prefix}.wrongsecret") is None

def test_authenticate_stamps_last_used(synced, db_tenant):
    with tenant_context(db_tenant):
        key, secret = iam.create_api_key("ci", [], creator_id=CREATOR, creator_perms=None)
        assert key.last_used_at is None
        iam.authenticate_api_key(secret)
        assert ApiKey.objects.get(id=key.id).last_used_at is not None
```

- [ ] **Step 2: Run them, verify they fail** — Run: `uv run pytest tests/test_apikey_service.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement** the service functions.
- [ ] **Step 4: Run them, verify they pass** — Expected: PASS.
- [ ] **Step 5: Commit** — `git add easybiz/core/iam/service.py tests/test_apikey_service.py && git commit -m "Add API key service (issue once, subset-scoped, constant-time auth, revoke/expiry)"`

---

### Task 3: Management endpoints

**Files:**
- Modify: `easybiz/core/kernel/core_permissions.py` (add `core.apikey.manage`)
- Modify: `easybiz/core/api/types.py` (`ApiKeyIn`, `ApiKeyOut`, `ApiKeyCreatedOut`)
- Modify: `easybiz/core/api/core_routes.py` (endpoints)
- Test: `tests/test_apikey_api.py`

**Interfaces:**
- `CORE_PERMISSIONS` gains `("core.apikey.manage", "Issue and revoke API keys")`.
- Types: `ApiKeyIn(name: str, permissions: list[str] = [], expires_at: str | None = None)`; `ApiKeyOut(id, name, prefix, permissions, created_at, expires_at, last_used_at, revoked_at — all str/None)`; `ApiKeyCreatedOut(ApiKeyOut + secret: str)` (the one-time full key).
- Endpoints (all `auth=perm("core.apikey.manage")`):
  - `GET /api/core/apikeys` → `list[ApiKeyOut]` (never includes a secret).
  - `POST /api/core/apikeys` → `{201: ApiKeyCreatedOut}` — calls `create_api_key(..., creator_id=request.auth.id, creator_perms=iam.permissions_for(request.auth.id))`; returns the key + the one-time `secret`.
  - `DELETE /api/core/apikeys/{key_id}` → `{204: None}` — `revoke_api_key`.

- [ ] **Step 1: Write the failing tests** (reuse the `_owner`/`_req`/`_limited_token` helper pattern)

```python
def test_requires_apikey_manage(synced, provision):
    from easybiz.core.tenancy.models import Tenant
    _owner(provision, "ak1")
    tok = _limited_token(Tenant.objects.get(slug="ak1"), ["core.user.read"])
    assert _req("get", "/api/core/apikeys", tok, "ak1").status_code == 403

def test_create_returns_secret_then_list_hides_it(synced, provision):
    token = _owner(provision, "ak2")
    r = _req("post", "/api/core/apikeys", token, "ak2", {"name": "ci", "permissions": ["core.audit.read"]})
    assert r.status_code == 201 and "." in r.json()["secret"]
    listed = _req("get", "/api/core/apikeys", token, "ak2").json()
    assert listed and "secret" not in listed[0]

def test_subset_rule_422(synced, provision):
    from easybiz.core.tenancy.models import Tenant
    _owner(provision, "ak3")
    tok = _limited_token(Tenant.objects.get(slug="ak3"), ["core.apikey.manage"])  # lacks core.user.manage
    r = _req("post", "/api/core/apikeys", tok, "ak3", {"name": "x", "permissions": ["core.user.manage"]})
    assert r.status_code == 422

def test_revoke(synced, provision):
    token = _owner(provision, "ak4")
    kid = _req("post", "/api/core/apikeys", token, "ak4", {"name": "ci"}).json()["id"]
    assert _req("delete", f"/api/core/apikeys/{kid}", token, "ak4").status_code == 204
```

- [ ] **Step 2: Run them, verify they fail** — Run: `uv run pytest tests/test_apikey_api.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement** the permission, types, and thin handlers (let `ApiKeyError` map via the central handler).
- [ ] **Step 4: Run them, verify they pass** — Expected: PASS.
- [ ] **Step 5: Guard existing permission tests** — Run: `uv run pytest tests/test_core_permissions.py tests/test_core_permissions_api.py -q` — Expected: PASS (update any exhaustive permission-set assertion to include `core.apikey.manage`).
- [ ] **Step 6: Run the full suite** — Run: `uv run pytest -q` — Expected: all pass.
- [ ] **Step 7: Commit** — `git add -A && git commit -m "Add /api/core/apikeys management endpoints under core.apikey.manage"`

---

## Post-implementation
- Update `README.md` Status with a short F13-apikeys paragraph (service credentials; subset-scoped; one-time secret; constant-time auth; revoke/expiry).
- **Security review before the PR** (standing instruction — this is an authentication/credential feature): `/security-review` on the branch; fix High/Medium; then open the PR.
- Deferred (noted): F23b applies these keys as a transport auth (on-behalf-of-user, tool allowlist, read/write scope, per-key rate limit) + the MCP wire server; the rest of F13 (refresh, reset, invitations, MFA, SSO, signing keys, brute-force, password policy) are separate slices.
