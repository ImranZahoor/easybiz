from __future__ import annotations

from typing import cast

from django.core.cache import cache
from django.db import connection


def _schema() -> str:
    return connection.schema_name  # type: ignore[attr-defined]  # django-tenants sets this


def role_version() -> int:
    """A per-schema counter bumped by any role or assignment change (never expires)."""
    return cast("int", cache.get_or_set(f"iam:ver:{_schema()}", 1, timeout=None))


def bump_role_version() -> None:
    """Invalidate every cached permission set for this schema (monotonic, non-expiring)."""
    cache.set(f"iam:ver:{_schema()}", role_version() + 1, timeout=None)


def cached_permissions_for(user_id) -> set[str]:
    """``service.permissions_for`` behind a 60s cache keyed by the role version."""
    from easybiz.core.iam import service  # lazy: service imports this module

    key = f"iam:perms:{_schema()}:{user_id}:{role_version()}"
    return cast("set[str]", cache.get_or_set(key, lambda: service.permissions_for(user_id), 60))


def cached_subject_attrs(user_id) -> dict:
    """``service.subject_attrs`` behind a 60s cache keyed by the role version."""
    from easybiz.core.iam import service

    key = f"iam:attrs:{_schema()}:{user_id}:{role_version()}"
    return cast("dict", cache.get_or_set(key, lambda: service.subject_attrs(user_id), 60))


def cached_active_policies() -> list[dict]:
    """Active policies (as plain dicts) behind a 60s cache keyed by the role version."""
    from easybiz.core.iam import service

    key = f"iam:policies:{_schema()}:{role_version()}"
    return cast("list[dict]", cache.get_or_set(key, service.active_policy_dicts, 60))
