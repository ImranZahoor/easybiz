"""DB router: a module's tables migrate into a tenant schema only when enabled."""

from __future__ import annotations

from django.db import connection
from django_tenants.routers import TenantSyncRouter
from django_tenants.utils import get_public_schema_name


def module_has_tables(schema_name: str, app_label: str) -> bool:
    """True if the tenant has any catalog_tenantmodule row for the module (any status)."""
    with connection.cursor() as cur:
        cur.execute(
            'SELECT 1 FROM "public".catalog_tenantmodule tm '
            'JOIN "public".tenancy_tenant t ON t.id = tm.tenant_id '
            "WHERE t.schema_name = %s AND tm.module_id = %s LIMIT 1",
            [schema_name, app_label],
        )
        return cur.fetchone() is not None


class ModuleAwareTenantSyncRouter(TenantSyncRouter):
    """Gates module apps by the catalog; non-module apps keep parent behaviour."""

    def _is_module_app(self, app_label: str) -> bool:
        from easybiz.core.kernel.registry import registry

        return registry.manifest(app_label) is not None

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        decision = super().allow_migrate(db, app_label, model_name, **hints)
        if not self._is_module_app(app_label):
            return decision
        schema = getattr(connection, "schema_name", None)
        if schema is None or schema == get_public_schema_name():
            return False
        return module_has_tables(schema, app_label)
