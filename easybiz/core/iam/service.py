from __future__ import annotations

from django.db.models import Q

from easybiz.core.catalog.models import Permission
from easybiz.core.iam.models import Role, RolePermission, UserRole
from easybiz.core.kernel import state
from easybiz.core.kernel.registry import registry


class RoleError(Exception):
    """Invalid role definition or assignment (maps to HTTP 422)."""


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


def assignable_permissions(tenant) -> set[str]:
    """Core permissions plus those of modules currently enabled for the tenant."""
    enabled = state.enabled_module_ids(tenant)
    return set(
        Permission.objects.filter(Q(module__isnull=True) | Q(module_id__in=enabled)).values_list(
            "code", flat=True
        )
    )


def role_permissions(role) -> list[str]:
    return sorted(role.permissions.values_list("permission", flat=True))


def create_role(tenant, name: str, permissions, description: str = "") -> Role:
    """Create a tenant role; rejects `*`, unknown/disabled perms, and duplicate names."""
    perms = list(permissions)
    if "*" in perms:
        raise RoleError("'*' is reserved for the system owner role")
    unknown = set(perms) - assignable_permissions(tenant)
    if unknown:
        raise RoleError(f"unknown or disabled permissions: {sorted(unknown)}")
    if Role.objects.filter(name=name).exists():
        raise RoleError(f"role {name!r} already exists")
    role = Role.objects.create(name=name, description=description, is_system=False)
    RolePermission.objects.bulk_create([RolePermission(role=role, permission=p) for p in perms])
    return role


def ensure_roles_exist(role_names) -> None:
    """Raise RoleError if any named role is missing (read-only; no writes)."""
    names = list(role_names)
    existing = set(Role.objects.filter(name__in=names).values_list("name", flat=True))
    missing = set(names) - existing
    if missing:
        raise RoleError(f"unknown roles: {sorted(missing)}")


def set_user_roles(user_id, role_names) -> None:
    """Replace the user's role set in the current tenant (RoleError on unknown role)."""
    names = list(role_names)
    roles = list(Role.objects.filter(name__in=names))
    missing = set(names) - {r.name for r in roles}
    if missing:
        raise RoleError(f"unknown roles: {sorted(missing)}")
    UserRole.objects.filter(user_id=user_id).delete()
    UserRole.objects.bulk_create([UserRole(user_id=user_id, role=r) for r in roles])
