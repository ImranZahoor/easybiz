from ninja import Router
from ninja.responses import Status

from easybiz.core.api.platform_security import platform_auth
from easybiz.core.platform_api import commands, queries
from easybiz.core.platform_api.types import (
    DomainIn,
    OverviewOut,
    TenantCreateIn,
    TenantListOut,
    TenantOut,
    TenantRenameIn,
)

router = Router()


@router.get("/overview", auth=platform_auth, response=OverviewOut)
def overview(request):
    """Headline counts for the operator dashboard."""
    return queries.overview()


@router.get("/tenants", auth=platform_auth, response=TenantListOut)
def list_tenants(
    request, q: str | None = None, is_active: bool | None = None, limit: int = 50, offset: int = 0
):
    """Tenants (the platform tenant excluded), optionally searched/filtered, paginated."""
    return queries.list_tenants(q, is_active, limit, offset)


@router.get("/tenants/{slug}", auth=platform_auth, response=TenantOut)
def get_tenant(request, slug: str):
    """One tenant by slug."""
    return queries.tenant_view(queries.require_tenant(slug))


@router.post("/tenants", auth=platform_auth, response={201: TenantOut})
def create_tenant(request, data: TenantCreateIn):
    """Provision a tenant (all-or-nothing); validation/conflict errors map to 422/409."""
    return Status(201, commands.create_tenant(request.auth, data))


@router.patch("/tenants/{slug}", auth=platform_auth, response=TenantOut)
def rename_tenant(request, slug: str, data: TenantRenameIn):
    """Rename a tenant."""
    return commands.rename_tenant(request.auth, slug, data.name)


@router.post("/tenants/{slug}/suspend", auth=platform_auth, response=TenantOut)
def suspend_tenant(request, slug: str):
    """Suspend a tenant (blocks its login, API and docs)."""
    return commands.suspend_tenant(request.auth, slug)


@router.post("/tenants/{slug}/resume", auth=platform_auth, response=TenantOut)
def resume_tenant(request, slug: str):
    """Resume a suspended tenant."""
    return commands.resume_tenant(request.auth, slug)


@router.delete("/tenants/{slug}", auth=platform_auth, response={204: None})
def delete_tenant(request, slug: str, confirm_slug: str = ""):
    """Delete a suspended tenant (requires confirm_slug == slug); keeps the people."""
    commands.delete_tenant(request.auth, slug, confirm_slug)
    return Status(204, None)


@router.post("/tenants/{slug}/domains", auth=platform_auth, response={201: TenantOut})
def add_tenant_domain(request, slug: str, data: DomainIn):
    """Attach a domain to a tenant (409 duplicate, 422 invalid)."""
    return Status(201, commands.add_domain(request.auth, slug, data.domain, data.is_primary))


@router.delete("/tenants/{slug}/domains/{domain}", auth=platform_auth, response=TenantOut)
def remove_tenant_domain(request, slug: str, domain: str):
    """Detach a domain (409 if it is the last, 422 if not a domain of the tenant)."""
    return commands.remove_domain(request.auth, slug, domain)
