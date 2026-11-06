from django.db.models import Q
from django_tenants.utils import get_public_schema_name
from ninja import Router
from ninja.errors import HttpError

from easybiz.core.api.platform_security import platform_auth
from easybiz.core.catalog.models import Module, TenantModule
from easybiz.core.platform_api.types import (
    DomainOut,
    OverviewOut,
    TenantListOut,
    TenantModuleOut,
    TenantOut,
)
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
