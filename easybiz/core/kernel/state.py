"""Enabled-module lookups that tolerate the pk-less stub tenant (I13)."""

from __future__ import annotations

from django_tenants.utils import get_public_schema_name

from easybiz.core.catalog.models import TenantModule


def _schema_name(tenant) -> str | None:
    return getattr(tenant, "schema_name", None)


def enabled_module_ids(tenant) -> set[str]:
    schema = _schema_name(tenant)
    if schema is None or schema == get_public_schema_name():
        return set()
    return set(
        TenantModule.objects.filter(
            tenant__schema_name=schema, status=TenantModule.ENABLED
        ).values_list("module_id", flat=True)
    )


def is_enabled(tenant, module_id: str) -> bool:
    return module_id in enabled_module_ids(tenant)
