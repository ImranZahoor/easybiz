# Easybiz Core M0 (Skeleton) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the repository skeleton so `uv run manage.py check` reports no issues and a smoke test boots Django.

**Architecture:** A Django project wired for `django-tenants` (schema-per-tenant) with `django-ninja` for the API. Code lives under one namespace package `easybiz`, split into `easybiz.core` (kernel + platform services) and `easybiz.modules` (business modules). M0 builds only the *import surface*: project config, the app packages, the tenancy/identity models that settings reference, and pass-through kernel stubs. No business logic, no migrations, no running endpoints yet. Boilerplate is generated with `django-admin`, then tailored — not hand-written.

**Tech Stack:** Python 3.13 (floor 3.12), Django ≥5.2 (resolves to latest 6.x), django-tenants ≥3.8, django-ninja ≥1.7, psycopg[binary] 3.x, PyJWT, django-cors-headers, python-dotenv; managed with `uv`; tested with `pytest`.

**Spec:** `ERP-CORE-SPEC.md` (this plan implements milestone **M0**, §11; settings §3.3–3.4; models §4.1; conventions §0.4–0.5).

## Global Constraints

Copied from the spec; every task inherits these.

- Python 3.13 pinned (`.python-version`), `requires-python = ">=3.12"`; Django `>=5.2`; django-tenants `>=3.8`; django-ninja `>=1.7`; PostgreSQL 16 via `psycopg[binary]` 3.x.
- Namespace: packages are `easybiz.core.*` and `easybiz.modules.*`; env prefix `EASYBIZ_`; DB `easybiz` (`easybiz_test` under pytest).
- Business entities use UUID primary keys (`uuid4`); infrastructure join tables use `BigAutoField`.
- Store UTC (`USE_TZ = True`); APIs exchange ISO 8601.
- `AUTH_USER_MODEL = "accounts.User"`; `django.contrib.auth` is **not** installed — use `AbstractBaseUser` and `auth.hashers` only; `PASSWORD_HASHERS` is PBKDF2 only.
- Module ids: `^[a-z][a-z0-9_]{1,30}$`; app label must equal the module id.
- Management command names must not collide with django-tenants commands.
- Conventions (§0.5): `uv` only (no pip/requirements); types in `types.py`; one `config/settings.py` (no env split); `.env` per environment; short imperative commit messages; **no co-author/attribution/emoji lines in commits**; docstrings on public classes/functions; comments only where the *why* is non-obvious; DRY/SOLID where they fit.
- Local lint/type gate must stay clean: `ruff` (lint + format) and `mypy` with `django-stubs`, configured in `pyproject.toml`.

## Review Focus

M0 is config/skeleton; these are the conditions most likely to bite that no happy-path test exercises. Each has a test pinned to its owning task.

- **Short/dev `SECRET_KEY` (P17):** the dev default must be ≥32 chars and production must require a real secret. → pinned in Task 5.
- **django-tenants system checks (P3, P4):** router set as both `TENANT_SYNC_ROUTER` and in `DATABASE_ROUTERS`; `django.contrib.contenttypes` installed. → pinned in Task 6.
- **Test DB selection under pytest (§3.3):** DB name resolves to `easybiz_test` when pytest is loaded, so tests never touch the dev DB. → pinned in Task 5.
- **pytest-django must be off (P11):** `addopts = -p no:django`. → pinned in Task 1.
- **Namespace imports resolve:** every dotted path in `INSTALLED_APPS`/`MIDDLEWARE`/`DATABASE_ROUTERS` imports under the `easybiz.*` namespace. → pinned in Task 6.

---

### Task 1: Project scaffold and dependencies (uv + django-admin)

**Files:**
- Create: `pyproject.toml`, `.python-version`, `docker-compose.yml`, `pytest.ini`, `.env.example`, `.gitignore`
- Generate (django-admin): `manage.py`, `config/__init__.py`, `config/settings.py`, `config/urls.py`, `config/asgi.py`

**Interfaces:**
- Consumes: nothing.
- Produces: an installed env, a generated Django project named `config`, and `uv run manage.py` dispatch (generated `manage.py` sets `DJANGO_SETTINGS_MODULE=config.settings`).

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[project]
name = "easybiz"
version = "0.1.0"
description = "Multi-tenant modular ERP core"
requires-python = ">=3.12"
dependencies = [
    "django>=5.2",
    "django-tenants>=3.8",
    "django-ninja>=1.7",
    "psycopg[binary]>=3.1",
    "pyjwt>=2.8",
    "django-cors-headers>=4.3",
    "python-dotenv>=1.0",
]

[dependency-groups]
dev = [
    "pytest>=8.0",
    "ruff>=0.6",
    "mypy>=1.11",
    "django-stubs[compatible-mypy]>=5.1",
]

[tool.uv]
package = false

[tool.ruff]
line-length = 100
target-version = "py312"
extend-exclude = ["**/migrations/*"]

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B"]

[tool.mypy]
python_version = "3.12"
plugins = ["mypy_django_plugin.main"]
ignore_missing_imports = true
warn_unused_ignores = true
exclude = ['/migrations/']

[tool.django-stubs]
django_settings_module = "config.settings"
```

- [ ] **Step 2: Write `.python-version`**

```
3.13
```

- [ ] **Step 3: Install and scaffold the Django project**

Run:
```bash
uv sync
uv run django-admin startproject config .
```
This generates `manage.py` and the `config/` package. Delete the generated `config/wsgi.py` (ASGI only).

- [ ] **Step 4: Write `docker-compose.yml`**

```yaml
services:
  db:
    image: postgres:16
    environment:
      POSTGRES_DB: easybiz
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
    ports:
      - "5432:5432"
    volumes:
      - easybiz_pgdata:/var/lib/postgresql/data

volumes:
  easybiz_pgdata:
```

- [ ] **Step 5: Write `pytest.ini`**

```ini
[pytest]
testpaths = tests easybiz
addopts = -q -p no:django
```

- [ ] **Step 6: Write `.env.example`**

```bash
DJANGO_SECRET_KEY=dev-insecure-change-me-00000000000000000000
DJANGO_DEBUG=1
DJANGO_ALLOWED_HOSTS=.localhost,127.0.0.1
EASYBIZ_DB_NAME=easybiz
EASYBIZ_DB_USER=postgres
EASYBIZ_DB_PASSWORD=postgres
EASYBIZ_DB_HOST=localhost
EASYBIZ_DB_PORT=5432
EASYBIZ_MODULES=easybiz.modules.timesheets
EASYBIZ_CORS_ORIGINS=
```

- [ ] **Step 7: Write `.gitignore`**

```
__pycache__/
*.pyc
.env
.venv/
staticfiles/
.pytest_cache/
```

- [ ] **Step 8: Verify dispatch**

Run: `uv run python -c "import django; print(django.get_version())"`
Expected: prints a version ≥ 5.2.

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "Scaffold uv project and Django config"
```

---

### Task 2: App packages (django-admin startapp) and Timesheets manifest

**Files:**
- Create: `easybiz/__init__.py`, `easybiz/core/__init__.py`, `easybiz/modules/__init__.py`
- Generate + tailor: `easybiz/core/{tenancy,accounts,catalog,iam,audit,events}/` and `easybiz/modules/timesheets/`
- Create: `easybiz/core/api/__init__.py`, `easybiz/core/platform_api/__init__.py`
- Create: `easybiz/modules/timesheets/manifest.json`

**Interfaces:**
- Consumes: nothing.
- Produces: importable Django apps whose `(name, label)` pairs match `SHARED_APPS`/`TENANT_APPS` in Task 6. `api`/`platform_api` are plain code packages (not in `INSTALLED_APPS`).

- [ ] **Step 1: Create namespace package markers**

`easybiz/__init__.py`, `easybiz/core/__init__.py`, `easybiz/modules/__init__.py` are empty.

- [ ] **Step 2: Generate the Django apps**

For each app below: `mkdir -p <path>` then `uv run django-admin startapp <label> <path>`.

| label | path |
|---|---|
| `tenancy` | `easybiz/core/tenancy` |
| `accounts` | `easybiz/core/accounts` |
| `catalog` | `easybiz/core/catalog` |
| `iam` | `easybiz/core/iam` |
| `audit` | `easybiz/core/audit` |
| `events` | `easybiz/core/events` |
| `timesheets` | `easybiz/modules/timesheets` |

- [ ] **Step 3: Prune generated boilerplate**

In every generated app delete `admin.py`, `views.py`, and `tests.py` (no Django admin; tests live in per-module `tests/` dirs per §0.5). Keep `apps.py`, `models.py`, `migrations/`.

- [ ] **Step 4: Fix each generated `apps.py`**

startapp sets `name = "<label>"`; change it to the full dotted path and add the label. Template:

```python
from django.apps import AppConfig


class <Label>Config(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "<dotted.path>"
    label = "<label>"
```

| `name` | `label` |
|---|---|
| `easybiz.core.tenancy` | `tenancy` |
| `easybiz.core.accounts` | `accounts` |
| `easybiz.core.catalog` | `catalog` |
| `easybiz.core.iam` | `iam` |
| `easybiz.core.audit` | `audit` |
| `easybiz.core.events` | `events` |
| `easybiz.modules.timesheets` | `timesheets` |

- [ ] **Step 5: Create plain code packages for the APIs**

`easybiz/core/api/__init__.py` and `easybiz/core/platform_api/__init__.py` are empty (routers mount in M4/M7; not Django apps).

- [ ] **Step 6: Create a minimal valid manifest**

`easybiz/modules/timesheets/manifest.json`:

```json
{
  "id": "timesheets",
  "name": "Timesheets",
  "version": "0.1.0",
  "requires": [],
  "optional": [],
  "provides": [],
  "consumes": [],
  "permissions": [],
  "roles": [],
  "events": {"publishes": [], "subscribes": []},
  "menu": []
}
```

- [ ] **Step 7: Verify imports**

Run: `uv run python -c "import easybiz.core.tenancy.apps, easybiz.core.accounts.apps, easybiz.modules.timesheets.apps; print('ok')"`
Expected: prints `ok`.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "Add easybiz.core and easybiz.modules app packages"
```

---

### Task 3: Kernel app and import-surface stubs

**Files:**
- Create: `easybiz/core/kernel/__init__.py`, `apps.py`, `middleware.py`, `routers.py`, `discovery.py`, `migrate.py`

**Interfaces:**
- Consumes: nothing.
- Produces: importable paths referenced by settings — `easybiz.core.kernel` (app, label `kernel`), `...middleware.TenantStatusMiddleware`, `...middleware.ModuleGateMiddleware`, `...routers.ModuleAwareTenantSyncRouter`, `...migrate.Command`, `...discovery.discover_module_packages`. All pass-through/minimal; real behaviour lands in M2–M4.

- [ ] **Step 1: `easybiz/core/kernel/__init__.py`** (empty)

- [ ] **Step 2: `easybiz/core/kernel/apps.py`**

```python
from django.apps import AppConfig


class KernelConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "easybiz.core.kernel"
    label = "kernel"

    def ready(self) -> None:
        """Registry loading is wired in M2; no-op at M0."""
```

- [ ] **Step 3: `easybiz/core/kernel/middleware.py`**

```python
class TenantStatusMiddleware:
    """Pass-through at M0; enforces tenant suspension in M4/M7."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)


class ModuleGateMiddleware:
    """Pass-through at M0; hides routes of disabled modules in M4."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)
```

- [ ] **Step 4: `easybiz/core/kernel/routers.py`**

```python
from django_tenants.routers import TenantSyncRouter


class ModuleAwareTenantSyncRouter(TenantSyncRouter):
    """Module-table gating is added in M3; inherits default behaviour at M0."""
```

- [ ] **Step 5: `easybiz/core/kernel/discovery.py`**

```python
from collections.abc import Iterable


def discover_module_packages(explicit: Iterable[str]) -> list[str]:
    """Return configured module packages; entry-point merge is added in M2."""
    return list(explicit)
```

- [ ] **Step 6: `easybiz/core/kernel/migrate.py`**

```python
from django.core.management.commands.migrate import Command as MigrateCommand


class Command(MigrateCommand):
    """Per-schema module-hiding is added in M3; base migrate at M0."""
```

- [ ] **Step 7: Verify imports**

Run: `uv run python -c "from easybiz.core.kernel import middleware, routers, discovery, migrate; print('ok')"`
Expected: prints `ok`.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "Add kernel app and import stubs"
```

---

### Task 4: Tenancy and accounts models

**Files:**
- Overwrite: `easybiz/core/tenancy/models.py`
- Overwrite: `easybiz/core/accounts/models.py`

**Interfaces:**
- Consumes: the `tenancy`/`accounts` apps from Task 2.
- Produces: `tenancy.Tenant`, `tenancy.Domain`, `accounts.User` (USERNAME_FIELD `email`, manager `create_user`), `accounts.Membership`. These resolve `TENANT_MODEL`, `TENANT_DOMAIN_MODEL`, `AUTH_USER_MODEL` in Task 5.

- [ ] **Step 1: Write `easybiz/core/tenancy/models.py`**

```python
from django.db import models
from django_tenants.models import DomainMixin, TenantMixin


class Tenant(TenantMixin):
    """One customer organisation; owns one PostgreSQL schema."""

    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=40, unique=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    auto_create_schema = True
    auto_drop_schema = False


class Domain(DomainMixin):
    """A host name mapped to a tenant."""
```

- [ ] **Step 2: Write `easybiz/core/accounts/models.py`**

```python
import uuid

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.db import models


class UserManager(BaseUserManager):
    """Creates global users; email is normalised to lowercase."""

    def create_user(self, email: str, password: str | None = None, **extra):
        if not email:
            raise ValueError("email is required")
        user = self.model(email=self.normalize_email(email).lower(), **extra)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user


class User(AbstractBaseUser):
    """Global identity; tenant access is granted through Membership."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True)
    name = models.CharField(max_length=200, blank=True)
    is_active = models.BooleanField(default=True)
    is_platform_admin = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []

    objects = UserManager()


class Membership(models.Model):
    """A user's active access to one tenant."""

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    tenant = models.ForeignKey(
        "tenancy.Tenant", on_delete=models.CASCADE, related_name="memberships"
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "tenant"], name="uniq_membership")
        ]
```

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "Add tenancy and accounts models"
```

---

### Task 5: Django settings and URL configs

**Files:**
- Overwrite: `config/settings.py`, `config/urls.py`
- Create: `config/urls_public.py`
- Test: `tests/test_settings.py`

**Interfaces:**
- Consumes: apps, models, kernel stubs from Tasks 2–4.
- Produces: `config.settings` with the full tenancy/module wiring; `config.urls` (tenant `ROOT_URLCONF`) and `config.urls_public` (`PUBLIC_SCHEMA_URLCONF`, serves `/health`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_settings.py
import importlib


def test_secret_key_default_is_long_enough():
    settings = importlib.import_module("config.settings")
    assert len(settings.SECRET_KEY) >= 32


def test_db_name_is_test_db_under_pytest():
    settings = importlib.import_module("config.settings")
    assert settings.DATABASES["default"]["NAME"] == "easybiz_test"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_settings.py -v`
Expected: FAIL (the generated settings lacks this wiring / `tests/` not present yet).

- [ ] **Step 3: Overwrite `config/settings.py`**

```python
"""Single settings module (§0.5). Env differences come from a .env file."""
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from easybiz.core.kernel.discovery import discover_module_packages

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

RUNNING_PYTEST = "pytest" in sys.modules or "PYTEST_CURRENT_TEST" in os.environ

SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY", "dev-insecure-change-me-00000000000000000000"
)
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", ".localhost,127.0.0.1").split(",")

if not DEBUG and SECRET_KEY.startswith("dev-insecure"):
    raise RuntimeError("DJANGO_SECRET_KEY must be set in production")

EASYBIZ_MODULE_PACKAGES = discover_module_packages(
    [p for p in os.environ.get("EASYBIZ_MODULES", "easybiz.modules.timesheets").split(",") if p]
)

SHARED_APPS = [
    "django_tenants",
    "easybiz.core.kernel",
    "django.contrib.contenttypes",
    "django.contrib.staticfiles",
    "easybiz.core.tenancy",
    "easybiz.core.accounts",
    "easybiz.core.catalog",
    "ninja",
    "corsheaders",
]
TENANT_APPS = [
    "easybiz.core.iam",
    "easybiz.core.audit",
    "easybiz.core.events",
    *EASYBIZ_MODULE_PACKAGES,
]
INSTALLED_APPS = list(SHARED_APPS) + [a for a in TENANT_APPS if a not in SHARED_APPS]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django_tenants.middleware.main.TenantMainMiddleware",
    "easybiz.core.kernel.middleware.TenantStatusMiddleware",
    "easybiz.core.kernel.middleware.ModuleGateMiddleware",
    "django.middleware.common.CommonMiddleware",
]

ROOT_URLCONF = "config.urls"
PUBLIC_SCHEMA_URLCONF = "config.urls_public"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "APP_DIRS": True,
        "DIRS": [],
        "OPTIONS": {"context_processors": ["django.template.context_processors.request"]},
    }
]

DATABASES = {
    "default": {
        "ENGINE": "django_tenants.postgresql_backend",
        "NAME": "easybiz_test" if RUNNING_PYTEST else os.environ.get("EASYBIZ_DB_NAME", "easybiz"),
        "USER": os.environ.get("EASYBIZ_DB_USER", "postgres"),
        "PASSWORD": os.environ.get("EASYBIZ_DB_PASSWORD", "postgres"),
        "HOST": os.environ.get("EASYBIZ_DB_HOST", "localhost"),
        "PORT": os.environ.get("EASYBIZ_DB_PORT", "5432"),
    }
}

TENANT_MODEL = "tenancy.Tenant"
TENANT_DOMAIN_MODEL = "tenancy.Domain"
TENANT_SYNC_ROUTER = "easybiz.core.kernel.routers.ModuleAwareTenantSyncRouter"
TENANT_BASE_MIGRATE_COMMAND = "easybiz.core.kernel.migrate.Command"
DATABASE_ROUTERS = ("easybiz.core.kernel.routers.ModuleAwareTenantSyncRouter",)

AUTH_USER_MODEL = "accounts.User"
PASSWORD_HASHERS = ["django.contrib.auth.hashers.PBKDF2PasswordHasher"]

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

CORS_ALLOW_CREDENTIALS = False
CORS_ALLOWED_ORIGINS = [o for o in os.environ.get("EASYBIZ_CORS_ORIGINS", "").split(",") if o]
if DEBUG:
    CORS_ALLOWED_ORIGIN_REGEXES = [
        r"^http://(.+\.)?localhost(:\d+)?$",
        r"^http://127\.0\.0\.1(:\d+)?$",
    ]

EASYBIZ_JWT_TTL_SECONDS = int(os.environ.get("EASYBIZ_JWT_TTL_SECONDS", "3600"))
EASYBIZ_PLATFORM_JWT_TTL_SECONDS = int(os.environ.get("EASYBIZ_PLATFORM_JWT_TTL_SECONDS", "1800"))
EASYBIZ_EVENT_MAX_ATTEMPTS = 5

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
USE_TZ = True
```

- [ ] **Step 4: Overwrite `config/urls.py`**

```python
"""Tenant host URLs; auth/core/module routers mount in M4+."""
from django.urls import path

urlpatterns: list[path] = []
```

- [ ] **Step 5: Write `config/urls_public.py`**

```python
"""Platform host URLs: health now; platform API mounts in M7."""
from django.http import JsonResponse
from django.urls import path


def health(_request):
    """Liveness probe for the platform host."""
    return JsonResponse({"status": "ok", "scope": "platform"})


urlpatterns = [
    path("health", health),
]
```

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run pytest tests/test_settings.py -v`
Expected: PASS (both tests). (Create `tests/__init__.py` and `tests/conftest.py` from Task 6 first if collection errors on the settings module.)

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "Add settings and URL configs"
```

---

### Task 6: Smoke test and green `check`

**Files:**
- Create: `tests/__init__.py`, `tests/conftest.py`, `tests/test_smoke.py`, `README.md`

**Interfaces:**
- Consumes: the full project from Tasks 1–5.
- Produces: a passing `uv run manage.py check` and an in-process smoke test.

- [ ] **Step 1: Write the failing smoke test**

`tests/__init__.py` empty. `tests/conftest.py`:

```python
import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
```

`tests/test_smoke.py`:

```python
import django
from django.conf import settings


def test_django_boots_and_system_checks_pass():
    django.setup()
    from django.core.management import call_command

    call_command("check")  # raises SystemCheckError on any error-level issue


def test_router_registered_for_django_tenants():
    assert settings.TENANT_SYNC_ROUTER in settings.DATABASE_ROUTERS


def test_contenttypes_installed():
    assert "django.contrib.contenttypes" in settings.INSTALLED_APPS
```

- [ ] **Step 2: Run the smoke test**

Run: `uv run pytest tests/test_smoke.py -v`
Expected: initially may FAIL on a misconfigured dotted path or model. Read the error, fix it in the owning task's file (spec rule 0.2.5 — the library wins; record surprises in §12).

- [ ] **Step 3: Run the Django check directly**

Run: `uv run manage.py check`
Expected: `System check identified no issues`. On django-tenants `E001`/router errors, confirm `TENANT_MODEL`, `TENANT_DOMAIN_MODEL`, `TENANT_SYNC_ROUTER`, `DATABASE_ROUTERS` are set (P3) and `django.contrib.contenttypes` is installed (P4).

- [ ] **Step 4: Write `README.md`**

Concisely: prerequisites (`docker compose up -d db`, `uv sync`), the M0 state ("skeleton; `uv run manage.py check` passes; no migrations yet"), and the Appendix G cheat sheet (uv form).

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -v`
Expected: all tests pass.

- [ ] **Step 5b: Lint and type-check gate**

Run:
```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy easybiz config
```
Expected: all clean. Fix any findings (format with `uv run ruff format .`) before committing.

- [ ] **Step 6: Confirm the handoff to M1**

Run: `uv run manage.py makemigrations --check --dry-run`
Expected: reports pending migrations for `tenancy`/`accounts` — the expected entry into **M1** (makemigrations + `init_platform`). Note it in the README; do **not** author migrations in M0.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "Add smoke test and green system check"
```

---

## M0 Definition of Done

- [ ] `uv run manage.py check` reports no issues (spec M0 verification).
- [ ] `uv run pytest` is green.
- [ ] Repo layout, `pyproject.toml`/`uv.lock`, `docker-compose.yml`, `pytest.ini`, `config/settings.py`, URL confs, and the `easybiz.core.*` / `easybiz.modules.*` packages exist (spec §3.2, §11 M0).
- [ ] Conventions honoured: `uv` only, short commit messages, no attribution lines, docstrings on public classes/functions.
- [ ] README reflects the M0 state and points at M1 as next.
```
