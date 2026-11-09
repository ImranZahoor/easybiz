from __future__ import annotations

from typing import cast

from django.core.cache import cache
from django.db import connection


def _schema() -> str:
    return connection.schema_name  # type: ignore[attr-defined]  # django-tenants sets this


def role_version() -> int:
    """A per-schema counter bumped by any role or assignment change."""
    return cast("int", cache.get_or_set(f"iam:ver:{_schema()}", 1))


def bump_role_version() -> None:
    """Invalidate every cached permission set for this schema."""
    cache.set(f"iam:ver:{_schema()}", role_version() + 1)


def cached_permissions_for(user_id) -> set[str]:
    """``service.permissions_for`` behind a 60s cache keyed by the role version."""
    from easybiz.core.iam import service  # lazy: service imports this module

    key = f"iam:perms:{_schema()}:{user_id}:{role_version()}"
    return cast("set[str]", cache.get_or_set(key, lambda: service.permissions_for(user_id), 60))
