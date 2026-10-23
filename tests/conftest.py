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


@pytest.fixture(autouse=True)
def _reset_capabilities():
    """Isolate the process-global capability registry between tests."""
    from easybiz.core.kernel import capabilities

    saved = dict(capabilities._providers)
    yield
    capabilities._providers.clear()
    capabilities._providers.update(saved)


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


@pytest.fixture
def provision():
    """Provision tenants and drop their schemas + owner users afterwards."""
    created: list[tuple[str, str]] = []  # (schema_name, owner_email)

    def _provision(slug="acme", modules=(), **over):
        from easybiz.core.kernel import provisioning

        params = {
            "name": slug.title(),
            "slug": slug,
            "domain": f"{slug}.localhost",
            "owner_email": f"owner@{slug}.test",
            "owner_password": "change-me-now",
            "modules": modules,
        }
        params.update(over)
        tenant = provisioning.provision_tenant(**params)
        created.append((tenant.schema_name, params["owner_email"]))
        return tenant

    yield _provision

    from easybiz.core.tenancy.models import Tenant
    from easybiz.core.users.models import User

    connection.set_schema_to_public()
    for schema, email in created:
        with connection.cursor() as cur:
            cur.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        Tenant.objects.filter(schema_name=schema).delete()
        User.objects.filter(email=email).delete()
