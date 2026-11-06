from ninja import Router
from ninja.errors import HttpError
from ninja.responses import Status

from easybiz.core.api.platform_security import platform_auth
from easybiz.core.catalog.models import Module, TenantModule
from easybiz.core.kernel import lifecycle
from easybiz.core.kernel.registry import registry
from easybiz.core.platform_api.tenants import _get_tenant_or_404, _tenant_view
from easybiz.core.platform_api.types import (
    ModuleCatalogOut,
    ModulePermOut,
    ModulesOut,
    TenantOut,
)
from easybiz.core.tenancy.audit import record_platform

router = Router()


def _catalog_view(module_id: str) -> ModuleCatalogOut:
    manifest = registry.manifest(module_id)  # on-disk code, or None
    row = Module.objects.filter(id=module_id).first()  # catalog entry, or None
    if manifest and row:
        state = "upgrade_pending" if row.version != manifest.version else "installed"
    elif manifest:
        state = "not_installed"
    else:
        state = "missing_code"
    return ModuleCatalogOut(
        id=module_id,
        name=manifest.name if manifest else (row.name if row else module_id),
        code_version=manifest.version if manifest else None,
        catalog_version=row.version if row else None,
        state=state,
        requires=[dep for dep, _ in manifest.requires] if manifest else [],
        optional=[dep for dep, _ in manifest.optional] if manifest else [],
        provides=list(manifest.provides) if manifest else [],
        publishes=list(manifest.publishes) if manifest else [],
        subscribes=list(manifest.subscribes) if manifest else [],
        permissions=[ModulePermOut(code=c, description=d) for c, d in manifest.permissions]
        if manifest
        else [],
        tenants_enabled=TenantModule.objects.filter(
            module_id=module_id, status=TenantModule.ENABLED
        ).count(),
        tenants_disabled=TenantModule.objects.filter(
            module_id=module_id, status=TenantModule.DISABLED
        ).count(),
    )


# --- fixed /modules routes MUST precede /modules/{id} (pitfall P8) -----------


@router.get("/modules", auth=platform_auth, response=list[ModuleCatalogOut])
def list_modules(request):
    """Every module known to the code or the catalog, with per-tenant counts and state."""
    ids = sorted(set(registry.module_ids()) | set(Module.objects.values_list("id", flat=True)))
    return [_catalog_view(mid) for mid in ids]


@router.post("/modules/sync", auth=platform_auth, response=ModulesOut)
def sync_modules(request):
    """Refresh the catalog from on-disk manifests (no tenant migrations)."""
    order = lifecycle.sync_catalog()
    record_platform(request.auth, "modules.synced", detail={"modules": order})
    return ModulesOut(modules=order)


@router.post("/modules/upgrade", auth=platform_auth, response=ModulesOut)
def upgrade_modules(request):
    """Refresh the catalog and migrate every tenant schema (synchronous)."""
    order = lifecycle.upgrade_modules()
    record_platform(request.auth, "modules.upgraded", detail={"modules": order})
    return ModulesOut(modules=order)


@router.get("/modules/{module_id}", auth=platform_auth, response=ModuleCatalogOut)
def get_module(request, module_id: str):
    """One catalog entry."""
    known = set(registry.module_ids()) | set(Module.objects.values_list("id", flat=True))
    if module_id not in known:
        raise HttpError(404, "module not found")
    return _catalog_view(module_id)


# --- per-tenant module lifecycle from the platform --------------------------


@router.post("/tenants/{slug}/modules/{module_id}/enable", auth=platform_auth, response=TenantOut)
def enable_tenant_module(request, slug: str, module_id: str):
    """Enable a module for a tenant."""
    tenant = _get_tenant_or_404(slug)
    lifecycle.enable_module(tenant, module_id, actor_id=request.auth.id)
    record_platform(
        request.auth, "tenant.module_enabled", target=slug, detail={"module": module_id}
    )
    return _tenant_view(tenant)


@router.post("/tenants/{slug}/modules/{module_id}/disable", auth=platform_auth, response=TenantOut)
def disable_tenant_module(request, slug: str, module_id: str):
    """Disable a module for a tenant."""
    tenant = _get_tenant_or_404(slug)
    lifecycle.disable_module(tenant, module_id, actor_id=request.auth.id)
    record_platform(
        request.auth, "tenant.module_disabled", target=slug, detail={"module": module_id}
    )
    return _tenant_view(tenant)


@router.delete(
    "/tenants/{slug}/modules/{module_id}/data", auth=platform_auth, response={200: TenantOut}
)
def remove_tenant_module_data(request, slug: str, module_id: str, confirm: bool = False):
    """Drop a disabled module's tables for a tenant (requires confirm=true)."""
    if not confirm:
        raise HttpError(400, "pass ?confirm=true to remove module data")
    tenant = _get_tenant_or_404(slug)
    lifecycle.remove_module_data(tenant, module_id, actor_id=request.auth.id)
    record_platform(
        request.auth, "tenant.module_data_removed", target=slug, detail={"module": module_id}
    )
    return Status(200, _tenant_view(tenant))
