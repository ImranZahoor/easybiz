"""Single settings module (§0.5). Env differences come from a .env file."""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from easybiz.core.kernel.discovery import discover_module_packages

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

RUNNING_PYTEST = "pytest" in sys.modules or "PYTEST_CURRENT_TEST" in os.environ

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-insecure-change-me-00000000000000000000")
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", ".localhost,127.0.0.1").split(",")

if not DEBUG and SECRET_KEY.startswith("dev-insecure"):
    raise RuntimeError("DJANGO_SECRET_KEY must be set in production")

EASYBIZ_MODULE_PACKAGES = discover_module_packages(
    [
        p
        for p in os.environ.get(
            "EASYBIZ_MODULES", "easybiz.modules.timesheets,easybiz.modules.demo"
        ).split(",")
        if p
    ]
)

SHARED_APPS = [
    "django_tenants",
    "easybiz.core.kernel",
    "django.contrib.contenttypes",
    "django.contrib.staticfiles",
    "easybiz.core.tenancy",
    "easybiz.core.users",
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

AUTH_USER_MODEL = "users.User"
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
