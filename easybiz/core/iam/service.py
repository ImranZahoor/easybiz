"""Authorization helpers: a user's effective permissions, wildcard checks, menu."""

from __future__ import annotations

from easybiz.core.iam.models import RolePermission, UserRole
from easybiz.core.kernel import state
from easybiz.core.kernel.registry import registry


def permissions_for(user_id) -> set[str]:
    """Union of the permission codes of the user's roles in the current schema."""
    role_ids = UserRole.objects.filter(user_id=user_id).values_list("role_id", flat=True)
    return set(
        RolePermission.objects.filter(role_id__in=role_ids).values_list("permission", flat=True)
    )


def has_permission(perms: set[str], code: str) -> bool:
    """True if the set grants ``code`` via ``*``, an exact match, or a ``module.*`` prefix."""
    if "*" in perms or code in perms:
        return True
    return f"{code.split('.')[0]}.*" in perms


def menu_for(tenant, perms: set[str]) -> list[dict]:
    """Menu items from enabled modules' manifests, filtered by each item's permission."""
    items: list[dict] = []
    for module_id in sorted(state.enabled_module_ids(tenant)):
        manifest = registry.manifest(module_id)
        for item in manifest.menu if manifest else []:
            needed = item.get("permission")
            if needed is None or has_permission(perms, needed):
                items.append({"module": module_id, "label": item["label"], "route": item["route"]})
    return items
