from ninja import Router
from ninja.responses import Status

from easybiz.core.api.platform_security import platform_auth
from easybiz.core.platform_api import commands, queries
from easybiz.core.platform_api.types import ModuleCatalogOut, ModulesOut, TenantOut

router = Router()


# --- fixed /modules routes MUST precede /modules/{id} (pitfall P8) -----------


@router.get("/modules", auth=platform_auth, response=list[ModuleCatalogOut])
def list_modules(request):
    """Every module known to the code or the catalog, with per-tenant counts and state."""
    return queries.module_catalog()


@router.post("/modules/sync", auth=platform_auth, response=ModulesOut)
def sync_modules(request):
    """Refresh the catalog from on-disk manifests (no tenant migrations)."""
    return ModulesOut(modules=commands.sync_modules(request.auth))


@router.post("/modules/upgrade", auth=platform_auth, response=ModulesOut)
def upgrade_modules(request):
    """Refresh the catalog and migrate every tenant schema (synchronous)."""
    return ModulesOut(modules=commands.upgrade_modules(request.auth))


@router.get("/modules/{module_id}", auth=platform_auth, response=ModuleCatalogOut)
def get_module(request, module_id: str):
    """One catalog entry."""
    return queries.module_entry(module_id)


# --- per-tenant module lifecycle from the platform --------------------------


@router.post("/tenants/{slug}/modules/{module_id}/enable", auth=platform_auth, response=TenantOut)
def enable_tenant_module(request, slug: str, module_id: str):
    """Enable a module for a tenant."""
    return commands.enable_module(request.auth, slug, module_id)


@router.post("/tenants/{slug}/modules/{module_id}/disable", auth=platform_auth, response=TenantOut)
def disable_tenant_module(request, slug: str, module_id: str):
    """Disable a module for a tenant."""
    return commands.disable_module(request.auth, slug, module_id)


@router.delete(
    "/tenants/{slug}/modules/{module_id}/data", auth=platform_auth, response={200: TenantOut}
)
def remove_tenant_module_data(request, slug: str, module_id: str, confirm: bool = False):
    """Drop a disabled module's tables for a tenant (requires confirm=true)."""
    return Status(200, commands.remove_module_data(request.auth, slug, module_id, confirm))
