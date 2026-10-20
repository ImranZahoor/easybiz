# Easybiz M1 (Tenancy & Identity) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Author the tenancy/identity migrations, add an idempotent `init_platform` command that creates the public tenant + its domain, and prove `/health` answers on the platform host — all against real PostgreSQL.

**Architecture:** The models already exist from M0 (`tenancy.Tenant/Domain`, `users.User/Membership`, all in SHARED_APPS → public schema). M1 makes them real: generate migrations, apply them to `public` via `migrate_schemas --shared`, seed the `public` tenant row + `localhost` domain with `init_platform`, and stand up the pytest DB harness (recreate `easybiz_test`, migrate, init) that every later DB test builds on.

**Tech Stack:** Django 6.1 + django-tenants (schema-per-tenant), PostgreSQL 16 (via `docker compose up -d db`), psycopg 3, pytest; managed with `uv`.

**Spec:** `ERP-CORE-SPEC.md` — M1 (§11), `init_platform` (§3.5), provisioning/tenancy (§6.1), data model (§4.1), test harness (§9), invariants I3/I12/I13/I15.

## Scope decision (please note)

The spec's §3.5 describes `init_platform` as "create the public tenant and its domain; fill the module catalog," and M1 says "then catalog sync." But the catalog models (`Module`, `TenantModule`, `Permission`) and `sync_catalog()` are **M3**. **Ruling:** M1's `init_platform` creates the **public tenant + domain only**; the catalog-sync step is added to `init_platform` in M3 when those models exist. This defers (rather than pulls forward) M3 scope, and `init_platform` stays idempotent so M3 can extend it. The M1 verify ("`init_platform` succeeds; `/health` returns ok") does not require catalog rows.

## Global Constraints

- Python 3.13 (floor 3.12); Django ≥5.2 (running 6.1); django-tenants ≥3.8; PostgreSQL 16 via `psycopg[binary]` 3.x. `uv` only.
- Namespace `easybiz.core.*` / `easybiz.modules.*`; env prefix `EASYBIZ_`; DB `easybiz` (`easybiz_test` under pytest).
- **I3:** tenant data only in tenant schema; platform/shared data only in `public`. **I15:** tests run against real PostgreSQL — no SQLite, no DB mocks. **I12:** `migrate_schemas` resets the connection to `public`; restore afterward.
- Store UTC (`USE_TZ=True`). Migrations are generated with `makemigrations` and committed — never hand-written (spec §0.2).
- §0.5: short imperative commits, no attribution lines; docstrings on public classes/functions; types in `types.py`; lint/type gate (`ruff`, `mypy easybiz config`) stays clean.
- Management command names must not collide with django-tenants (`init_platform` is unique — OK).

## Review Focus

Each pinned to the task that owns it.

- **`init_platform` idempotency:** running it twice must not duplicate rows or error. → Task 3.
- **Public-schema special-casing (I13-adjacent):** creating the `public` Tenant row must not attempt to create/migrate the `public` schema. → Task 3.
- **`localhost` host resolves to the public tenant:** `/health` must answer 200 with the platform payload via `TenantMainMiddleware` + the `localhost` domain. → Task 4.
- **Shared-only migration (I4/I3):** `migrate_schemas --shared` creates core/shared tables in `public` and **no** module tables (`timesheets_*`). → Task 2.
- **Test-DB isolation (I15):** the harness recreates `easybiz_test` and never touches the dev `easybiz` DB. → Task 2 (DB name already pinned by `tests/test_settings.py`).

---

### Task 1: Author tenancy & identity migrations

**Files:**
- Create (generated): `easybiz/core/tenancy/migrations/0001_initial.py`, `easybiz/core/users/migrations/0001_initial.py`

**Interfaces:**
- Consumes: the M0 models `tenancy.Tenant/Domain`, `users.User/Membership`.
- Produces: initial migrations for apps `tenancy` and `users` (shared apps). No DB needed to generate.

- [ ] **Step 1: Generate the migrations**

Run: `uv run manage.py makemigrations tenancy users`
Expected: creates `0001_initial.py` under each app's `migrations/` (Create Tenant, Domain, User, Membership).

- [ ] **Step 2: Verify no migrations are left unmade**

Run: `uv run manage.py makemigrations --check --dry-run`
Expected: `No changes detected` (exit 0).

- [ ] **Step 3: Lint/type gate (generated migrations are excluded)**

Run: `uv run ruff check . && uv run mypy easybiz config`
Expected: clean (ruff/mypy both exclude `migrations/`).

- [ ] **Step 4: Commit**

```bash
git add easybiz/core/tenancy/migrations easybiz/core/users/migrations
git commit -m "Add initial migrations for tenancy and users"
```

---

### Task 2: Test DB harness + shared migrations applied

**Files:**
- Modify: `tests/conftest.py`
- Create: `tests/test_shared_schema.py`

**Interfaces:**
- Consumes: Task 1 migrations; `config.settings` DATABASES (`easybiz_test`).
- Produces: a session-scoped `platform` fixture that recreates `easybiz_test` and runs `migrate_schemas --shared`; a function-scoped autouse fixture resetting the connection to `public`; a `tables_in` fixture. (Task 3 extends `platform` to also run `init_platform`.)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_shared_schema.py
def test_shared_core_tables_exist_in_public(tables_in):
    tables = tables_in("public")
    assert {"tenancy_tenant", "tenancy_domain", "users_user", "users_membership"} <= tables


def test_module_tables_absent_from_public(tables_in):
    assert "timesheets_entry" not in tables_in("public")
```

- [ ] **Step 2: Run it — expect failure (no harness yet)**

Run: `uv run pytest tests/test_shared_schema.py -v`
Expected: FAIL — `tables_in` fixture undefined (and no DB set up).

- [ ] **Step 3: Extend `tests/conftest.py` with the DB harness**

```python
import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django

django.setup()

import psycopg
import pytest
from django.conf import settings
from django.core.management import call_command
from django.db import connection


def _recreate_test_db() -> None:
    """Drop and recreate the test database from the `postgres` maintenance DB."""
    db = settings.DATABASES["default"]
    name = db["NAME"]
    dsn = (
        f"host={db['HOST']} port={db['PORT']} user={db['USER']} "
        f"password={db['PASSWORD']} dbname=postgres"
    )
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        conn.execute(f'CREATE DATABASE "{name}"')


@pytest.fixture(scope="session", autouse=True)
def platform():
    """Fresh test DB with shared schema migrated. (init_platform added in M1 Task 3.)"""
    _recreate_test_db()
    call_command("migrate_schemas", "--shared", verbosity=0)
    yield


@pytest.fixture(autouse=True)
def _reset_schema():
    """Keep every test starting and ending on the public schema (I12/I13)."""
    connection.set_schema_to_public()
    yield
    connection.set_schema_to_public()


@pytest.fixture
def tables_in():
    def _tables_in(schema: str) -> set[str]:
        with connection.cursor() as cur:
            cur.execute("SELECT tablename FROM pg_tables WHERE schemaname = %s", [schema])
            return {row[0] for row in cur.fetchall()}

    return _tables_in
```

- [ ] **Step 4: Run with the DB up — expect pass**

Run: `docker compose up -d db && uv run pytest tests/test_shared_schema.py -v`
Expected: PASS (both). If `migrate_schemas` errors on connection, confirm the db container is healthy (`docker compose ps`).

- [ ] **Step 5: Full suite stays green**

Run: `uv run pytest`
Expected: all pass (M0 smoke/settings tests + the two new ones).

- [ ] **Step 6: Commit**

```bash
git add tests/conftest.py tests/test_shared_schema.py
git commit -m "Add pytest DB harness and shared-schema migration test"
```

---

### Task 3: `init_platform` command (public tenant + domain)

**Files:**
- Create: `easybiz/core/kernel/management/__init__.py`, `easybiz/core/kernel/management/commands/__init__.py`, `easybiz/core/kernel/management/commands/init_platform.py`
- Modify: `tests/conftest.py` (add `init_platform` to the `platform` fixture)
- Create: `tests/test_init_platform.py`

**Interfaces:**
- Consumes: `tenancy.Tenant`, `tenancy.Domain`; the `platform` fixture from Task 2.
- Produces: management command `init_platform [--domain localhost]`; a seeded `public` Tenant (`schema_name="public"`, `slug="platform"`, `name="Platform"`) and a primary `Domain`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_init_platform.py
from django.core.management import call_command

from easybiz.core.tenancy.models import Domain, Tenant


def test_public_tenant_and_domain_exist():
    tenant = Tenant.objects.get(schema_name="public")
    assert tenant.slug == "platform"
    domain = Domain.objects.get(tenant=tenant)
    assert domain.domain == "localhost"
    assert domain.is_primary is True


def test_init_platform_is_idempotent():
    call_command("init_platform", "--domain", "localhost", verbosity=0)
    call_command("init_platform", "--domain", "localhost", verbosity=0)
    assert Tenant.objects.filter(schema_name="public").count() == 1
    assert Domain.objects.filter(domain="localhost").count() == 1
```

- [ ] **Step 2: Run it — expect failure**

Run: `uv run pytest tests/test_init_platform.py -v`
Expected: FAIL — `init_platform` command does not exist / public tenant not seeded (the Task 2 fixture doesn't run it yet).

- [ ] **Step 3: Implement the command**

```python
# easybiz/core/kernel/management/commands/init_platform.py
from django.core.management.base import BaseCommand
from django.db import transaction

from easybiz.core.tenancy.models import Domain, Tenant


class Command(BaseCommand):
    """Create the public (platform) tenant and its primary domain. Idempotent."""

    help = "Create the public tenant and its primary domain."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--domain", default="localhost")

    @transaction.atomic
    def handle(self, *args, **options) -> None:
        tenant, created = Tenant.objects.get_or_create(
            schema_name="public",
            defaults={"slug": "platform", "name": "Platform"},
        )
        Domain.objects.get_or_create(
            domain=options["domain"],
            tenant=tenant,
            defaults={"is_primary": True},
        )
        self.stdout.write(
            f"public tenant {'created' if created else 'exists'}; domain {options['domain']}"
        )
```

(`management/__init__.py` and `management/commands/__init__.py` are empty.)

- [ ] **Step 4: Wire `init_platform` into the session fixture**

In `tests/conftest.py`, add the `init_platform` call to the `platform` fixture:

```python
@pytest.fixture(scope="session", autouse=True)
def platform():
    """Fresh test DB with shared schema migrated and the public tenant seeded."""
    _recreate_test_db()
    call_command("migrate_schemas", "--shared", verbosity=0)
    call_command("init_platform", "--domain", "localhost", verbosity=0)
    yield
```

- [ ] **Step 5: Run it — expect pass**

Run: `uv run pytest tests/test_init_platform.py -v`
Expected: PASS. If saving the public Tenant tries to create the `public` schema and errors, that is the P-class public-schema pitfall — django-tenants skips schema creation for `PUBLIC_SCHEMA_NAME`; confirm `schema_name="public"` exactly (library wins — adjust and note in spec §12).

- [ ] **Step 6: Commit**

```bash
git add easybiz/core/kernel/management tests/conftest.py tests/test_init_platform.py
git commit -m "Add init_platform command seeding the public tenant"
```

---

### Task 4: `/health` on the platform host + docs

**Files:**
- Create: `tests/test_health.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: the running public tenant + `localhost` domain (from the `platform` fixture); `config/urls_public.py::health` (exists since M0).
- Produces: an integration test proving host→tenant resolution serves the platform health payload.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_health.py
from django.test import Client


def test_health_on_platform_host():
    resp = Client().get("/health", HTTP_HOST="localhost")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "scope": "platform"}
```

- [ ] **Step 2: Run it**

Run: `uv run pytest tests/test_health.py -v`
Expected: PASS (public tenant + localhost domain resolve to `config.urls_public`). If 404, confirm the `localhost` Domain exists and `PUBLIC_SCHEMA_URLCONF = "config.urls_public"`.

- [ ] **Step 3: Full suite + gate**

Run: `uv run pytest && uv run ruff check . && uv run ruff format --check . && uv run mypy easybiz config`
Expected: all green.

- [ ] **Step 4: Update `README.md`**

Update the Status section to: M1 complete — tenancy/identity migrations applied, `init_platform` seeds the public tenant, `/health` answers on `localhost`. Document `docker compose up -d db` as a test prerequisite and add `uv run manage.py migrate_schemas --shared` + `uv run manage.py init_platform` to the commands list.

- [ ] **Step 5: Commit**

```bash
git add tests/test_health.py README.md
git commit -m "Add platform health test and M1 README"
```

---

## M1 Definition of Done

- [ ] `uv run manage.py makemigrations --check --dry-run` → `No changes detected`.
- [ ] `docker compose up -d db` then `uv run pytest` → all green (M0 + M1 tests) against real PostgreSQL.
- [ ] `migrate_schemas --shared` creates shared core tables in `public`; no module tables present.
- [ ] `init_platform` creates the public tenant + `localhost` domain and is idempotent.
- [ ] `/health` on `localhost` returns `{"status":"ok","scope":"platform"}`.
- [ ] `ruff` + `mypy easybiz config` clean; README reflects M1; commits short with no attribution.
