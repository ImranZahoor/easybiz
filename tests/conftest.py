import os

import django
import psycopg
import pytest
from django.conf import settings
from django.core.management import call_command
from django.db import connection

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()


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
    """Fresh test DB with shared schema migrated and the public tenant seeded."""
    _recreate_test_db()
    call_command("migrate_schemas", "--shared", verbosity=0)
    call_command("init_platform", "--domain", "localhost", verbosity=0)
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


@pytest.fixture
def db_tenant():
    """A throwaway tenant schema (t_state) with core tenant apps migrated."""
    from easybiz.core.tenancy.models import Domain, Tenant

    tenant = Tenant(schema_name="t_state", slug="state", name="State")
    tenant.save()  # auto_create_schema migrates core tenant apps into t_state
    Domain.objects.create(domain="state.localhost", tenant=tenant, is_primary=True)
    connection.set_schema_to_public()
    yield tenant
    with connection.cursor() as cur:
        cur.execute('DROP SCHEMA IF EXISTS "t_state" CASCADE')
    Tenant.objects.filter(schema_name="t_state").delete()


@pytest.fixture
def synced():
    """Populate the catalog from the modules on disk."""
    from easybiz.core.kernel import lifecycle

    lifecycle.sync_catalog()
