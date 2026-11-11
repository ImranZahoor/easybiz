from __future__ import annotations

from django.contrib.auth.hashers import check_password, make_password
from django.db.models import Q
from django_tenants.utils import get_public_schema_name

from easybiz.core.catalog.models import Module, TenantModule
from easybiz.core.errors import DomainError
from easybiz.core.kernel.registry import registry
from easybiz.core.platform_api.types import (
    AdminOut,
    DomainOut,
    ModuleCatalogOut,
    ModulePermOut,
    OverviewOut,
    PlatformAuditOut,
    TenantListOut,
    TenantModuleOut,
    TenantOut,
)
from easybiz.core.tenancy.models import Domain, PlatformAuditLog, Tenant
from easybiz.core.users.models import Membership, User

# A real hash to verify against on the login miss path, so a non-admin email costs the
# same time as a real one and cannot be enumerated by response latency.
_DUMMY_HASH = make_password("platform-login-timing-equalizer")


def authenticate_platform(email: str, password: str) -> User | None:
    """Return the active platform admin for valid credentials, else None (constant-time)."""
    user = User.objects.filter(email=email.lower(), is_active=True, is_platform_admin=True).first()
    if user is None:
        check_password(password, _DUMMY_HASH)
        return None
    if not user.check_password(password):
        return None
    return user


def require_tenant(slug: str) -> Tenant:
    """A real tenant by slug, or a 404 domain error (the platform tenant is not a tenant)."""
    tenant = Tenant.objects.filter(slug=slug).exclude(schema_name=get_public_schema_name()).first()
    if tenant is None:
        raise DomainError("tenant not found", 404)
    return tenant


def tenant_view(tenant: Tenant) -> TenantOut:
    """Serialise a tenant with its domains, modules, and active-member count."""
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


def overview() -> OverviewOut:
    tenants = Tenant.objects.exclude(schema_name=get_public_schema_name())
    return OverviewOut(
        tenants_total=tenants.count(),
        tenants_active=tenants.filter(is_active=True).count(),
        tenants_suspended=tenants.filter(is_active=False).count(),
        platform_admins=User.objects.filter(is_platform_admin=True, is_active=True).count(),
        modules_installed=Module.objects.count(),
    )


def list_tenants(q: str | None, is_active: bool | None, limit: int, offset: int) -> TenantListOut:
    qs = Tenant.objects.exclude(schema_name=get_public_schema_name()).order_by("slug")
    if q:
        qs = qs.filter(Q(slug__icontains=q) | Q(name__icontains=q))
    if is_active is not None:
        qs = qs.filter(is_active=is_active)
    count = qs.count()
    limit = max(0, min(limit, 200))
    return TenantListOut(count=count, items=[tenant_view(t) for t in qs[offset : offset + limit]])


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
        provides=[c for c, _ in manifest.provides] if manifest else [],
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


def _module_ids() -> set[str]:
    return set(registry.module_ids()) | set(Module.objects.values_list("id", flat=True))


def module_catalog() -> list[ModuleCatalogOut]:
    return [_catalog_view(mid) for mid in sorted(_module_ids())]


def module_entry(module_id: str) -> ModuleCatalogOut:
    if module_id not in _module_ids():
        raise DomainError("module not found", 404)
    return _catalog_view(module_id)


def admin_view(user: User) -> AdminOut:
    return AdminOut(id=str(user.id), email=user.email, name=user.name)


def list_admins() -> list[AdminOut]:
    admins = User.objects.filter(is_platform_admin=True, is_active=True).order_by("email")
    return [admin_view(u) for u in admins]


def list_audit(action: str | None, target: str | None, limit: int) -> list[PlatformAuditOut]:
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
