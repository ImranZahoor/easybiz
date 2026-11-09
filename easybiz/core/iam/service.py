from __future__ import annotations

from django.db.models import Q

from easybiz.core.audit import service as audit
from easybiz.core.catalog.models import Permission
from easybiz.core.errors import DomainError
from easybiz.core.events import service as events
from easybiz.core.iam import cache
from easybiz.core.iam.models import Role, RolePermission, UserRole
from easybiz.core.kernel import state
from easybiz.core.kernel.registry import registry


class RoleError(DomainError):
    """Invalid role definition or assignment (maps to HTTP 422)."""

    def __init__(self, message: str) -> None:
        super().__init__(message, 422)


def _ancestors(role: Role) -> list[Role]:
    """A role's parent chain (cycle-safe: stops if a role repeats)."""
    chain: list[Role] = []
    seen = {role.id}
    current = role.parent
    while current is not None and current.id not in seen:
        chain.append(current)
        seen.add(current.id)
        current = current.parent
    return chain


def effective_codes(role: Role) -> set[str]:
    """A role's own permission codes unioned with all its ancestors'."""
    role_ids = [role.id, *(a.id for a in _ancestors(role))]
    return set(
        RolePermission.objects.filter(role_id__in=role_ids).values_list("permission", flat=True)
    )


def would_cycle(role: Role, new_parent: Role | None) -> bool:
    """True if making ``new_parent`` the parent of ``role`` would form a cycle."""
    if new_parent is None:
        return False
    if new_parent.id == role.id:
        return True
    return role.id in {a.id for a in _ancestors(new_parent)}


def permissions_for(user_id) -> set[str]:
    """Union of the effective (own + inherited) permission codes of the user's roles."""
    roles = Role.objects.filter(assignments__user_id=user_id).select_related("parent").distinct()
    perms: set[str] = set()
    for role in roles:
        perms |= effective_codes(role)
    return perms


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


def permission_groups(tenant) -> list[dict]:
    """Assignable permissions grouped by module ("core" for core permissions)."""
    enabled = state.enabled_module_ids(tenant)
    rows = Permission.objects.filter(Q(module__isnull=True) | Q(module_id__in=enabled)).order_by(
        "code"
    )
    groups: dict[str, list[dict]] = {}
    for p in rows:
        groups.setdefault(p.module_id or "core", []).append(
            {"code": p.code, "description": p.description}
        )
    return [{"module": m, "permissions": perms} for m, perms in sorted(groups.items())]


def _get_role(role_id) -> Role:
    role = Role.objects.filter(id=role_id).first()
    if role is None:
        raise DomainError("role not found", 404)
    return role


def _assert_assignable(tenant, perms) -> None:
    """Permissions must be real + enabled for the tenant, and never the reserved `*`."""
    if "*" in perms:
        raise RoleError("'*' is reserved for the system owner role")
    unknown = set(perms) - assignable_permissions(tenant)
    if unknown:
        raise RoleError(f"unknown or disabled permissions: {sorted(unknown)}")


def _assert_grantable(perms, actor_perms) -> None:
    """Nobody grants a permission they don't hold (``actor_perms`` None or ``*`` = unrestricted)."""
    if actor_perms is None or "*" in actor_perms:
        return
    ungrantable = sorted(p for p in perms if not has_permission(actor_perms, p))
    if ungrantable:
        raise RoleError(f"cannot grant permissions you do not hold: {ungrantable}")


def _snapshot(role: Role) -> dict:
    return {
        "name": role.name,
        "description": role.description,
        "is_system": role.is_system,
        "parent": role.parent.name if role.parent else None,
        "permissions": role_permissions(role),
    }


def _announce(actor_id, action: str, role_name: str, before, after) -> None:
    audit.record(actor_id, action, entity="role", entity_id=role_name, before=before, after=after)
    events.publish("core.role.changed", {"role": role_name}, producer="core")
    cache.bump_role_version()


def _resolve_parent(name):
    if name is None:
        return None
    parent = Role.objects.filter(name=name).first()
    if parent is None:
        raise RoleError(f"unknown parent role {name!r}")
    return parent


def create_role(tenant, name: str, permissions, description: str = "", actor_perms=None) -> Role:
    """Create a tenant role; rejects `*`/unknown perms, escalation, and duplicate names."""
    perms = list(permissions)
    _assert_assignable(tenant, perms)
    _assert_grantable(perms, actor_perms)
    if Role.objects.filter(name=name).exists():
        raise RoleError(f"role {name!r} already exists")
    role = Role.objects.create(name=name, description=description, is_system=False)
    RolePermission.objects.bulk_create([RolePermission(role=role, permission=p) for p in perms])
    events.publish("core.role.changed", {"role": name}, producer="core")
    cache.bump_role_version()
    return role


def update_role(tenant, role_id, *, actor_id, actor_perms, changes: dict) -> Role:
    """Apply only the provided fields (name/description/permissions/parent) with guards."""
    role = _get_role(role_id)
    before = _snapshot(role)
    if role.is_system and set(changes) - {"description"}:
        raise RoleError("a system role allows only a description change")
    if "name" in changes:
        if Role.objects.filter(name=changes["name"]).exclude(id=role.id).exists():
            raise RoleError(f"role {changes['name']!r} already exists")
        role.name = changes["name"]
    if "description" in changes:
        role.description = changes["description"]
    if "parent" in changes:
        new_parent = _resolve_parent(changes["parent"])
        if would_cycle(role, new_parent):
            raise RoleError("parent would create an inheritance cycle")
        if new_parent is not None:
            # inheriting a parent grants its permissions, so the actor must hold them
            _assert_grantable(effective_codes(new_parent), actor_perms)
        role.parent = new_parent
    role.save()
    if "permissions" in changes:
        _assert_assignable(tenant, changes["permissions"])
        _assert_grantable(changes["permissions"], actor_perms)
        role.permissions.all().delete()
        RolePermission.objects.bulk_create(
            [RolePermission(role=role, permission=p) for p in changes["permissions"]]
        )
    _announce(actor_id, "role.updated", role.name, before, _snapshot(role))
    return role


def delete_role(role_id, *, force: bool, actor_id) -> None:
    """Delete a non-system role; refuse if still assigned unless ``force``."""
    role = _get_role(role_id)
    if role.is_system:
        raise DomainError("a system role cannot be deleted", 409)
    if UserRole.objects.filter(role=role).exists() and not force:
        raise DomainError("role is assigned; pass ?force=true to delete", 409)
    before = _snapshot(role)
    name = role.name
    role.delete()  # cascades RolePermission + UserRole
    _announce(actor_id, "role.deleted", name, before, None)


def clone_role(tenant, role_id, new_name: str, *, actor_id, actor_perms) -> Role:
    """Duplicate a role's own permissions + parent under a new name, grant-guarded."""
    src = _get_role(role_id)
    own = list(src.permissions.values_list("permission", flat=True))
    _assert_assignable(tenant, own)
    _assert_grantable(effective_codes(src), actor_perms)  # includes inherited, to block escalation
    if Role.objects.filter(name=new_name).exists():
        raise RoleError(f"role {new_name!r} already exists")
    clone = Role.objects.create(
        name=new_name, description=src.description, is_system=False, parent=src.parent
    )
    RolePermission.objects.bulk_create([RolePermission(role=clone, permission=p) for p in own])
    _announce(actor_id, "role.cloned", new_name, None, _snapshot(clone))
    return clone


def ensure_roles_exist(role_names) -> None:
    """Raise RoleError if any named role is missing (read-only; no writes)."""
    names = list(role_names)
    existing = set(Role.objects.filter(name__in=names).values_list("name", flat=True))
    missing = set(names) - existing
    if missing:
        raise RoleError(f"unknown roles: {sorted(missing)}")


def _assert_can_assign(role_names, actor_perms) -> None:
    """You can only assign a role whose effective permissions you already hold."""
    if actor_perms is None or "*" in actor_perms:
        return
    for role in Role.objects.filter(name__in=role_names):
        if any(not has_permission(actor_perms, c) for c in effective_codes(role)):
            raise RoleError(f"cannot assign role {role.name!r}: it grants permissions you lack")


def _owner_lost(user_id, new_role_names) -> bool:
    """True if this change strips the last remaining holder of the ``owner`` role."""
    has_owner = UserRole.objects.filter(user_id=user_id, role__name="owner").exists()
    if not has_owner or "owner" in new_role_names:
        return False
    return not UserRole.objects.filter(role__name="owner").exclude(user_id=user_id).exists()


def would_orphan_owner(user_id) -> bool:
    """True if removing this user entirely would leave the tenant with no owner."""
    return _owner_lost(user_id, set())


def _announce_user(actor_id, action: str, user_id) -> None:
    audit.record(actor_id, action, entity="user", entity_id=str(user_id))
    events.publish("core.role.changed", {"user": str(user_id)}, producer="core")
    cache.bump_role_version()


def set_user_roles(user_id, role_names, *, actor_id=None, actor_perms=None) -> None:
    """Replace the user's role set, with assign-escalation and last-owner guards."""
    names = list(role_names)
    roles = list(Role.objects.filter(name__in=names))
    missing = set(names) - {r.name for r in roles}
    if missing:
        raise RoleError(f"unknown roles: {sorted(missing)}")
    _assert_can_assign(names, actor_perms)
    if _owner_lost(user_id, names):
        raise DomainError("cannot remove the last owner", 409)
    UserRole.objects.filter(user_id=user_id).delete()
    UserRole.objects.bulk_create([UserRole(user_id=user_id, role=r) for r in roles])
    _announce_user(actor_id, "user.roles_set", user_id)


def add_user_role(user_id, role_name, *, actor_id=None, actor_perms=None) -> None:
    """Grant one role to a user (assign-escalation guarded)."""
    role = Role.objects.filter(name=role_name).first()
    if role is None:
        raise RoleError(f"unknown role {role_name!r}")
    _assert_can_assign([role_name], actor_perms)
    UserRole.objects.get_or_create(user_id=user_id, role=role)
    _announce_user(actor_id, "user.role_added", user_id)


def remove_user_role(user_id, role_name, *, actor_id=None) -> None:
    """Remove one role from a user (last-owner guarded)."""
    role = Role.objects.filter(name=role_name).first()
    if role is None:
        raise RoleError(f"unknown role {role_name!r}")
    current = set(UserRole.objects.filter(user_id=user_id).values_list("role__name", flat=True))
    if _owner_lost(user_id, current - {role_name}):
        raise DomainError("cannot remove the last owner", 409)
    UserRole.objects.filter(user_id=user_id, role=role).delete()
    _announce_user(actor_id, "user.role_removed", user_id)
