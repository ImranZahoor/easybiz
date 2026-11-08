from ninja import Router
from ninja.responses import Status

from easybiz.core.api.platform_security import platform_auth
from easybiz.core.platform_api import commands, queries
from easybiz.core.platform_api.types import AdminIn, AdminOut, PlatformAuditOut

router = Router()


@router.get("/admins", auth=platform_auth, response=list[AdminOut])
def list_admins(request):
    """Active platform admins."""
    return queries.list_admins()


@router.post("/admins", auth=platform_auth, response={201: AdminOut})
def add_admin(request, data: AdminIn):
    """Create a platform admin (password required) or promote an existing user."""
    return Status(201, commands.add_admin(request.auth, data))


@router.delete("/admins/{admin_id}", auth=platform_auth, response={204: None})
def remove_admin(request, admin_id: str):
    """Demote a platform admin; cannot remove yourself or the last admin."""
    commands.remove_admin(request.auth, admin_id)
    return Status(204, None)


@router.get("/audit", auth=platform_auth, response=list[PlatformAuditOut])
def list_audit(request, action: str | None = None, target: str | None = None, limit: int = 50):
    """The platform audit log, newest first (limit capped at 200)."""
    return queries.list_audit(action, target, limit)
