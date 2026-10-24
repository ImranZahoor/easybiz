"""Tenant audit log writer (writes in the caller's schema and transaction)."""

from __future__ import annotations

from uuid import UUID

from easybiz.core.audit.models import AuditLog


def record(
    actor_id: UUID | None,
    action: str,
    entity: str = "",
    entity_id: str = "",
    before: dict | None = None,
    after: dict | None = None,
) -> AuditLog:
    """Write one tenant audit row for a sensitive action."""
    return AuditLog.objects.create(
        actor_id=actor_id,
        action=action,
        entity=entity,
        entity_id=entity_id,
        before=before,
        after=after,
    )
