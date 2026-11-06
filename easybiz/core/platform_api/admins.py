from django.db import transaction
from ninja import Router
from ninja.errors import HttpError
from ninja.responses import Status

from easybiz.core.api.platform_security import platform_auth
from easybiz.core.platform_api.types import AdminIn, AdminOut, PlatformAuditOut
from easybiz.core.tenancy.audit import record_platform
from easybiz.core.tenancy.models import PlatformAuditLog
from easybiz.core.users.models import User
from easybiz.core.users.service import WeakPassword

router = Router()


def _admin_view(user: User) -> AdminOut:
    return AdminOut(id=str(user.id), email=user.email, name=user.name)


@router.get("/admins", auth=platform_auth, response=list[AdminOut])
def list_admins(request):
    """Active platform admins."""
    admins = User.objects.filter(is_platform_admin=True, is_active=True).order_by("email")
    return [_admin_view(u) for u in admins]


@router.post("/admins", auth=platform_auth, response={201: AdminOut})
def add_admin(request, data: AdminIn):
    """Create a platform admin (password required) or promote an existing user."""
    user = User.objects.filter(email=data.email.lower()).first()
    if user is None:
        if not data.password or len(data.password) < 10:
            raise WeakPassword("a new platform admin needs a password of at least 10 characters")
        user = User.objects.create_user(
            email=data.email, password=data.password, name=data.name or "", is_platform_admin=True
        )
    else:
        if data.password:
            user.set_password(data.password)
        user.is_platform_admin = True
        user.save(
            update_fields=["is_platform_admin", "password"]
            if data.password
            else ["is_platform_admin"]
        )
    record_platform(request.auth, "admin.added", target=user.email)
    return Status(201, _admin_view(user))


@router.delete("/admins/{admin_id}", auth=platform_auth, response={204: None})
def remove_admin(request, admin_id: str):
    """Demote a platform admin; cannot remove yourself or the last admin."""
    if str(request.auth.id) == admin_id:
        raise HttpError(409, "you cannot remove yourself")
    with transaction.atomic():
        # Lock the admin set so concurrent removals can't both pass the count check.
        admins = list(
            User.objects.select_for_update().filter(is_platform_admin=True, is_active=True)
        )
        user = next((u for u in admins if str(u.id) == admin_id), None)
        if user is None:
            raise HttpError(404, "platform admin not found")
        if len(admins) <= 1:
            raise HttpError(409, "cannot remove the last platform admin")
        user.is_platform_admin = False
        user.save(update_fields=["is_platform_admin"])
    record_platform(request.auth, "admin.removed", target=user.email)
    return Status(204, None)


@router.get("/audit", auth=platform_auth, response=list[PlatformAuditOut])
def list_audit(request, action: str | None = None, target: str | None = None, limit: int = 50):
    """The platform audit log, newest first (limit capped at 200)."""
    rows = PlatformAuditLog.objects.all().order_by("-at")
    if action:
        rows = rows.filter(action=action)
    if target:
        rows = rows.filter(target=target)
    return [
        PlatformAuditOut(
            at=r.at.isoformat(),
            actor_email=r.actor_email,
            action=r.action,
            target=r.target,
            detail=r.detail,
        )
        for r in rows[: max(0, min(limit, 200))]
    ]
