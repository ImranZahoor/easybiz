from __future__ import annotations

from django.db import connection

from easybiz.core.api import paging
from easybiz.core.audit.models import AuditLog
from easybiz.core.catalog.models import TenantModule
from easybiz.core.iam import service as iam
from easybiz.core.kernel import state
from easybiz.core.kernel.registry import registry as module_registry
from easybiz.core.tools.enums import ToolTier
from easybiz.core.tools.paging_io import PageIn
from easybiz.core.tools.registry import Tool, registry
from easybiz.core.users.models import Membership


def _tenant():
    return connection.tenant  # set by the request / tenant_context


def _context(user_id, params):
    tenant = _tenant()
    return {
        "tenant": {"slug": tenant.slug, "name": tenant.name},
        "enabled_modules": sorted(state.enabled_module_ids(tenant)),
    }


def _modules(user_id, params):
    tenant = _tenant()
    enabled = state.enabled_module_ids(tenant)
    out = []
    for mid in sorted(module_registry.module_ids()):
        manifest = module_registry.manifest(mid)
        if mid in enabled:
            status = "enabled"
        elif TenantModule.objects.filter(tenant=tenant, module_id=mid).exists():
            status = "disabled"
        else:
            status = "available"
        out.append(
            {
                "id": mid,
                "name": manifest.name if manifest else mid,
                "version": manifest.version if manifest else "",
                "status": status,
            }
        )
    return out


def _roles(user_id, params):
    return [
        {
            "id": str(r.id),
            "name": r.name,
            "description": r.description,
            "is_system": r.is_system,
            "permissions": iam.role_permissions(r),
        }
        for r in iam.list_roles()
    ]


def _permissions(user_id, params):
    return iam.permission_groups(_tenant())


def _users(user_id, params):
    members = Membership.objects.filter(tenant=_tenant(), is_active=True).select_related("user")
    return [
        {"id": str(m.user.id), "email": m.user.email, "roles": iam.user_role_names(m.user.id)}
        for m in members
    ]


def _audit(user_id, params):
    page = paging.paginate(
        AuditLog.objects.all(), limit=params.limit, cursor=params.cursor, order_by="-at"
    )
    items = [
        {
            "at": r.at.isoformat(),
            "actor_id": str(r.actor_id) if r.actor_id else None,
            "action": r.action,
            "entity": r.entity,
            "entity_id": r.entity_id,
        }
        for r in page["items"]
    ]
    return {"items": items, "next_cursor": page["next_cursor"]}


_CORE_TOOLS = [
    Tool(
        "core.context",
        "The current tenant and its enabled modules.",
        ToolTier.READ,
        None,
        True,
        None,
        _context,
    ),
    Tool(
        "core.modules.list",
        "Installed modules and their per-tenant status.",
        ToolTier.READ,
        "core.module.read",
        True,
        None,
        _modules,
    ),
    Tool(
        "core.roles.list",
        "Roles in this tenant with their permissions.",
        ToolTier.READ,
        "core.role.read",
        True,
        None,
        _roles,
    ),
    Tool(
        "core.permissions.list",
        "Assignable permissions grouped by module.",
        ToolTier.READ,
        "core.role.read",
        True,
        None,
        _permissions,
    ),
    Tool(
        "core.users.list",
        "Active members of this tenant and their roles.",
        ToolTier.READ,
        "core.user.read",
        True,
        None,
        _users,
    ),
    Tool(
        "core.audit.list",
        "The tenant audit log, newest first.",
        ToolTier.READ,
        "core.audit.read",
        True,
        PageIn,
        _audit,
    ),
]


def register_core_tools() -> None:
    """Register the core read tools (idempotent — safe to call at startup)."""
    for tool in _CORE_TOOLS:
        if registry.get(tool.name) is None:
            registry.register(tool)
