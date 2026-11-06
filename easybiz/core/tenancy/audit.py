from __future__ import annotations

from easybiz.core.tenancy.models import PlatformAuditLog


def record_platform(
    actor, action: str, target: str = "", detail: dict | None = None
) -> PlatformAuditLog:
    """Record one platform operator action in the public schema."""
    return PlatformAuditLog.objects.create(
        actor_id=getattr(actor, "id", None),
        actor_email=getattr(actor, "email", "") or "",
        action=action,
        target=target,
        detail=detail or {},
    )
