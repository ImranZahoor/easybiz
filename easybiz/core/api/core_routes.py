from __future__ import annotations

from uuid import UUID

from django.db import transaction
from ninja import Router
from ninja.errors import HttpError
from ninja.responses import Status

from easybiz.core.api.security import authenticated, perm
from easybiz.core.api.types import (
    AuditOut,
    ContextOut,
    ModuleOut,
    RoleCloneIn,
    RoleIn,
    RoleOut,
    RoleUpdateIn,
    TenantSummary,
    UserIn,
    UserOut,
    UserRolesIn,
)
from easybiz.core.audit import service as audit
from easybiz.core.audit.models import AuditLog
from easybiz.core.catalog.models import TenantModule
from easybiz.core.events import service as events
from easybiz.core.iam import service as iam
from easybiz.core.iam.models import Role, UserRole
from easybiz.core.kernel import lifecycle, state
from easybiz.core.kernel.registry import registry
from easybiz.core.users import service as users
from easybiz.core.users.models import Membership, User

router = Router()


@router.get("/context", auth=authenticated, response=ContextOut)
def context(request):
    """Tenant bootstrap for any signed-in user: the tenant and its enabled modules."""
    tenant = request.tenant
    return ContextOut(
        tenant=TenantSummary(slug=tenant.slug, name=tenant.name),
        enabled_modules=sorted(state.enabled_module_ids(tenant)),
    )


def _module_view(tenant, module_id: str) -> ModuleOut:
    manifest = registry.manifest(module_id)
    enabled = state.enabled_module_ids(tenant)
    has_row = TenantModule.objects.filter(tenant=tenant, module_id=module_id).exists()
    if module_id in enabled:
        status = "enabled"
    elif has_row:
        status = "disabled"
    else:
        status = "available"
    requires = [dep for dep, _ in manifest.requires] if manifest else []
    optional = [dep for dep, _ in manifest.optional] if manifest else []
    if status == "enabled":
        blocked_by = [d for d in registry.dependents_of(module_id) if d in enabled]
    else:
        blocked_by = [d for d in requires if d not in enabled]
    return ModuleOut(
        id=module_id,
        name=manifest.name if manifest else module_id,
        version=manifest.version if manifest else "",
        status=status,
        requires=requires,
        optional=optional,
        blocked_by=blocked_by,
    )


@router.get("/modules", auth=perm("core.module.read"), response=list[ModuleOut])
def list_modules(request):
    """Every installed module with its per-tenant status and dependency blockers."""
    return [_module_view(request.tenant, mid) for mid in sorted(registry.module_ids())]


@router.post("/modules/{module_id}/enable", auth=perm("core.module.manage"), response=ModuleOut)
def enable(request, module_id: str):
    try:
        lifecycle.enable_module(request.tenant, module_id, actor_id=request.auth.id)
    except lifecycle.LifecycleError as exc:
        raise HttpError(409, str(exc)) from exc
    return _module_view(request.tenant, module_id)


@router.post("/modules/{module_id}/disable", auth=perm("core.module.manage"), response=ModuleOut)
def disable(request, module_id: str):
    try:
        lifecycle.disable_module(request.tenant, module_id, actor_id=request.auth.id)
    except lifecycle.LifecycleError as exc:
        raise HttpError(409, str(exc)) from exc
    return _module_view(request.tenant, module_id)


@router.delete("/modules/{module_id}/data", auth=perm("core.module.manage"), response=ModuleOut)
def remove_data(request, module_id: str, confirm: bool = False):
    if not confirm:
        raise HttpError(400, "pass ?confirm=true to remove module data")
    try:
        lifecycle.remove_module_data(request.tenant, module_id, actor_id=request.auth.id)
    except lifecycle.LifecycleError as exc:
        raise HttpError(409, str(exc)) from exc
    return _module_view(request.tenant, module_id)


def _role_view(role) -> RoleOut:
    return RoleOut(
        id=str(role.id),
        name=role.name,
        description=role.description,
        is_system=role.is_system,
        permissions=iam.role_permissions(role),
    )


@router.get("/roles", auth=perm("core.role.read"), response=list[RoleOut])
def list_roles(request):
    return [_role_view(r) for r in Role.objects.order_by("name")]


@router.post("/roles", auth=perm("core.role.manage"), response={201: RoleOut})
def create_role(request, data: RoleIn):
    role = iam.create_role(
        request.tenant,
        data.name,
        data.permissions,
        data.description,
        actor_perms=iam.permissions_for(request.auth.id),
    )
    audit.record(request.auth.id, "role.created", entity="role", entity_id=str(role.id))
    return Status(201, _role_view(role))


@router.patch("/roles/{role_id}", auth=perm("core.role.manage"), response=RoleOut)
def update_role(request, role_id: str, data: RoleUpdateIn):
    """Change name/description/permissions/parent (system roles: description only)."""
    role = iam.update_role(
        request.tenant,
        role_id,
        actor_id=request.auth.id,
        actor_perms=iam.permissions_for(request.auth.id),
        changes=data.model_dump(exclude_unset=True),
    )
    return _role_view(role)


@router.delete("/roles/{role_id}", auth=perm("core.role.manage"), response={204: None})
def delete_role(request, role_id: str, force: bool = False):
    """Delete a non-system role; needs ?force=true if still assigned."""
    iam.delete_role(role_id, force=force, actor_id=request.auth.id)
    return Status(204, None)


@router.post("/roles/{role_id}/clone", auth=perm("core.role.manage"), response={201: RoleOut})
def clone_role(request, role_id: str, data: RoleCloneIn):
    """Duplicate a role's permissions and parent under a new name."""
    role = iam.clone_role(
        request.tenant,
        role_id,
        data.name,
        actor_id=request.auth.id,
        actor_perms=iam.permissions_for(request.auth.id),
    )
    return Status(201, _role_view(role))


def _user_view(user) -> UserOut:
    role_names = UserRole.objects.filter(user_id=user.id).values_list("role__name", flat=True)
    return UserOut(id=str(user.id), email=user.email, roles=sorted(role_names))


@router.get("/users", auth=perm("core.user.read"), response=list[UserOut])
def list_users(request):
    members = Membership.objects.filter(tenant=request.tenant, is_active=True).select_related(
        "user"
    )
    return [_user_view(m.user) for m in members]


@router.post("/users", auth=perm("core.user.manage"), response={201: UserOut})
def create_user(request, data: UserIn):
    try:
        with transaction.atomic():
            iam.ensure_roles_exist(data.roles)  # validate before any write
            user = users.create_user(
                data.email, request.tenant, password=data.password, name=data.name
            )
            iam.set_user_roles(
                user.id,
                data.roles,
                actor_id=request.auth.id,
                actor_perms=iam.permissions_for(request.auth.id),
            )
    except (users.WeakPassword, iam.RoleError) as exc:
        raise HttpError(422, str(exc)) from exc
    audit.record(request.auth.id, "user.added", entity="user", entity_id=str(user.id))
    return Status(201, _user_view(user))


@router.delete("/users/{user_id}", auth=perm("core.user.manage"), response={204: None})
def delete_user(request, user_id: str):
    if str(request.auth.id) == user_id:
        raise HttpError(409, "you cannot remove yourself")
    membership = Membership.objects.filter(tenant=request.tenant, user_id=user_id).first()
    if membership is None:
        raise HttpError(404, "user is not a member of this tenant")
    UserRole.objects.filter(user_id=user_id).delete()
    membership.delete()
    events.publish("core.membership.removed", {"user_id": user_id})
    audit.record(request.auth.id, "user.removed", entity="user", entity_id=user_id)
    return Status(204, None)


def _user_out(user_id: UUID) -> UserOut:
    user = User.objects.filter(id=user_id).first()
    if user is None:
        raise HttpError(404, "user not found")
    return _user_view(user)


@router.put("/users/{user_id}/roles", auth=perm("core.user.manage"), response=UserOut)
def set_user_roles(request, user_id: UUID, data: UserRolesIn):
    """Replace a user's role set."""
    iam.set_user_roles(
        user_id,
        data.roles,
        actor_id=request.auth.id,
        actor_perms=iam.permissions_for(request.auth.id),
    )
    return _user_out(user_id)


@router.post("/users/{user_id}/roles/{name}", auth=perm("core.user.manage"), response=UserOut)
def add_user_role(request, user_id: UUID, name: str):
    """Grant one role to a user."""
    iam.add_user_role(
        user_id, name, actor_id=request.auth.id, actor_perms=iam.permissions_for(request.auth.id)
    )
    return _user_out(user_id)


@router.delete("/users/{user_id}/roles/{name}", auth=perm("core.user.manage"), response=UserOut)
def remove_user_role(request, user_id: UUID, name: str):
    """Remove one role from a user."""
    iam.remove_user_role(user_id, name, actor_id=request.auth.id)
    return _user_out(user_id)


@router.get("/audit", auth=perm("core.audit.read"), response=list[AuditOut])
def list_audit(request, limit: int = 50):
    """The tenant audit log, newest first (limit capped at 200)."""
    rows = AuditLog.objects.order_by("-at")[: max(0, min(limit, 200))]
    return [
        AuditOut(
            at=r.at.isoformat(),
            actor_id=str(r.actor_id) if r.actor_id else None,
            action=r.action,
            entity=r.entity,
            entity_id=r.entity_id,
        )
        for r in rows
    ]
