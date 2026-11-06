from django.db.models import Q
from django_tenants.utils import get_public_schema_name
from ninja import Router
from ninja.errors import HttpError
from ninja.responses import Status

from easybiz.core.api.platform_security import platform_auth
from easybiz.core.catalog.models import Module, TenantModule
from easybiz.core.kernel import provisioning
from easybiz.core.kernel import tenants as tops
from easybiz.core.platform_api.types import (
    DomainIn,
    DomainOut,
    OverviewOut,
    TenantCreateIn,
    TenantListOut,
    TenantModuleOut,
    TenantOut,
    TenantRenameIn,
)
from easybiz.core.tenancy.audit import record_platform
from easybiz.core.tenancy.models import Domain, Tenant
from easybiz.core.users.models import Membership, User

router = Router()


def _tenant_view(tenant: Tenant) -> TenantOut:
    domains = [
        DomainOut(domain=d.domain, is_primary=d.is_primary)
        for d in Domain.objects.filter(tenant=tenant).order_by("domain")
    ]
    modules = [
        TenantModuleOut(
            module=tm.module_id, status=tm.status, installed_version=tm.installed_version or ""
        )
        for tm in TenantModule.objects.filter(tenant=tenant).order_by("module_id")
    ]
    return TenantOut(
        slug=tenant.slug,
        name=tenant.name,
        schema_name=tenant.schema_name,
        is_active=tenant.is_active,
        created_at=tenant.created_at.isoformat(),
        domains=domains,
        modules=modules,
        member_count=Membership.objects.filter(tenant=tenant, is_active=True).count(),
    )


def _get_tenant_or_404(slug: str) -> Tenant:
    tenant = Tenant.objects.filter(slug=slug).exclude(schema_name=get_public_schema_name()).first()
    if tenant is None:
        raise HttpError(404, "tenant not found")
    return tenant


@router.get("/overview", auth=platform_auth, response=OverviewOut)
def overview(request):
    """Headline counts for the operator dashboard."""
    tenants = Tenant.objects.exclude(schema_name=get_public_schema_name())
    return OverviewOut(
        tenants_total=tenants.count(),
        tenants_active=tenants.filter(is_active=True).count(),
        tenants_suspended=tenants.filter(is_active=False).count(),
        platform_admins=User.objects.filter(is_platform_admin=True, is_active=True).count(),
        modules_installed=Module.objects.count(),
    )


@router.get("/tenants", auth=platform_auth, response=TenantListOut)
def list_tenants(
    request, q: str | None = None, is_active: bool | None = None, limit: int = 50, offset: int = 0
):
    """Tenants (the platform tenant excluded), optionally searched/filtered, paginated."""
    qs = Tenant.objects.exclude(schema_name=get_public_schema_name()).order_by("slug")
    if q:
        qs = qs.filter(Q(slug__icontains=q) | Q(name__icontains=q))
    if is_active is not None:
        qs = qs.filter(is_active=is_active)
    count = qs.count()
    limit = max(0, min(limit, 200))
    items = [_tenant_view(t) for t in qs[offset : offset + limit]]
    return TenantListOut(count=count, items=items)


@router.get("/tenants/{slug}", auth=platform_auth, response=TenantOut)
def get_tenant(request, slug: str):
    """One tenant by slug."""
    return _tenant_view(_get_tenant_or_404(slug))


@router.post("/tenants", auth=platform_auth, response={201: TenantOut})
def create_tenant(request, data: TenantCreateIn):
    """Provision a tenant (all-or-nothing); validation/conflict errors map to 422/409."""
    tenant = provisioning.provision_tenant(
        name=data.name,
        slug=data.slug,
        domain=data.domain,
        owner_email=data.owner_email,
        owner_password=data.owner_password,
        modules=data.modules,
        actor_id=request.auth.id,
    )
    record_platform(
        request.auth, "tenant.created", target=data.slug, detail={"modules": list(data.modules)}
    )
    return Status(201, _tenant_view(tenant))


@router.patch("/tenants/{slug}", auth=platform_auth, response=TenantOut)
def rename_tenant(request, slug: str, data: TenantRenameIn):
    """Rename a tenant."""
    tenant = _get_tenant_or_404(slug)
    tenant.name = data.name
    tenant.save(update_fields=["name"])
    record_platform(request.auth, "tenant.renamed", target=slug, detail={"name": data.name})
    return _tenant_view(tenant)


@router.post("/tenants/{slug}/suspend", auth=platform_auth, response=TenantOut)
def suspend_tenant(request, slug: str):
    """Suspend a tenant (blocks its login, API and docs)."""
    tenant = _get_tenant_or_404(slug)
    tops.suspend(tenant)
    record_platform(request.auth, "tenant.suspended", target=slug)
    return _tenant_view(tenant)


@router.post("/tenants/{slug}/resume", auth=platform_auth, response=TenantOut)
def resume_tenant(request, slug: str):
    """Resume a suspended tenant."""
    tenant = _get_tenant_or_404(slug)
    tops.resume(tenant)
    record_platform(request.auth, "tenant.resumed", target=slug)
    return _tenant_view(tenant)


@router.delete("/tenants/{slug}", auth=platform_auth, response={204: None})
def delete_tenant(request, slug: str, confirm_slug: str = ""):
    """Delete a suspended tenant (requires confirm_slug == slug); keeps the people."""
    tenant = _get_tenant_or_404(slug)
    tops.delete_tenant(tenant, confirm_slug)
    record_platform(request.auth, "tenant.deleted", target=slug)
    return Status(204, None)


@router.post("/tenants/{slug}/domains", auth=platform_auth, response={201: TenantOut})
def add_tenant_domain(request, slug: str, data: DomainIn):
    """Attach a domain to a tenant (409 duplicate, 422 invalid)."""
    tenant = _get_tenant_or_404(slug)
    tops.add_domain(tenant, data.domain, is_primary=data.is_primary)
    record_platform(
        request.auth, "tenant.domain_added", target=slug, detail={"domain": data.domain}
    )
    return Status(201, _tenant_view(tenant))


@router.delete("/tenants/{slug}/domains/{domain}", auth=platform_auth, response=TenantOut)
def remove_tenant_domain(request, slug: str, domain: str):
    """Detach a domain (409 if it is the last, 422 if not a domain of the tenant)."""
    tenant = _get_tenant_or_404(slug)
    tops.remove_domain(tenant, domain)
    record_platform(request.auth, "tenant.domain_removed", target=slug, detail={"domain": domain})
    return _tenant_view(tenant)
