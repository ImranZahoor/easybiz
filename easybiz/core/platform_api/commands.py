from __future__ import annotations

from django.db import transaction

from easybiz.core.errors import DomainError
from easybiz.core.kernel import lifecycle, provisioning
from easybiz.core.kernel import tenants as tops
from easybiz.core.platform_api import queries
from easybiz.core.platform_api.types import AdminIn, AdminOut, TenantCreateIn, TenantOut
from easybiz.core.tenancy.audit import record_platform
from easybiz.core.users.models import User
from easybiz.core.users.service import WeakPassword

# --- tenants ----------------------------------------------------------------


def create_tenant(actor, data: TenantCreateIn) -> TenantOut:
    tenant = provisioning.provision_tenant(
        name=data.name,
        slug=data.slug,
        domain=data.domain,
        owner_email=data.owner_email,
        owner_password=data.owner_password,
        modules=data.modules,
        actor_id=actor.id,
    )
    record_platform(
        actor, "tenant.created", target=data.slug, detail={"modules": list(data.modules)}
    )
    return queries.tenant_view(tenant)


def rename_tenant(actor, slug: str, name: str) -> TenantOut:
    tenant = queries.require_tenant(slug)
    tenant.name = name
    tenant.save(update_fields=["name"])
    record_platform(actor, "tenant.renamed", target=slug, detail={"name": name})
    return queries.tenant_view(tenant)


def suspend_tenant(actor, slug: str) -> TenantOut:
    tenant = queries.require_tenant(slug)
    tops.suspend(tenant)
    record_platform(actor, "tenant.suspended", target=slug)
    return queries.tenant_view(tenant)


def resume_tenant(actor, slug: str) -> TenantOut:
    tenant = queries.require_tenant(slug)
    tops.resume(tenant)
    record_platform(actor, "tenant.resumed", target=slug)
    return queries.tenant_view(tenant)


def delete_tenant(actor, slug: str, confirm_slug: str) -> None:
    tenant = queries.require_tenant(slug)
    tops.delete_tenant(tenant, confirm_slug)
    record_platform(actor, "tenant.deleted", target=slug)


# --- domains ----------------------------------------------------------------


def add_domain(actor, slug: str, domain: str, is_primary: bool) -> TenantOut:
    tenant = queries.require_tenant(slug)
    tops.add_domain(tenant, domain, is_primary=is_primary)
    record_platform(actor, "tenant.domain_added", target=slug, detail={"domain": domain})
    return queries.tenant_view(tenant)


def remove_domain(actor, slug: str, domain: str) -> TenantOut:
    tenant = queries.require_tenant(slug)
    tops.remove_domain(tenant, domain)
    record_platform(actor, "tenant.domain_removed", target=slug, detail={"domain": domain})
    return queries.tenant_view(tenant)


# --- modules ----------------------------------------------------------------


def enable_module(actor, slug: str, module_id: str) -> TenantOut:
    tenant = queries.require_tenant(slug)
    lifecycle.enable_module(tenant, module_id, actor_id=actor.id)
    record_platform(actor, "tenant.module_enabled", target=slug, detail={"module": module_id})
    return queries.tenant_view(tenant)


def disable_module(actor, slug: str, module_id: str) -> TenantOut:
    tenant = queries.require_tenant(slug)
    lifecycle.disable_module(tenant, module_id, actor_id=actor.id)
    record_platform(actor, "tenant.module_disabled", target=slug, detail={"module": module_id})
    return queries.tenant_view(tenant)


def remove_module_data(actor, slug: str, module_id: str, confirm: bool) -> TenantOut:
    if not confirm:
        raise DomainError("pass ?confirm=true to remove module data", 400)
    tenant = queries.require_tenant(slug)
    lifecycle.remove_module_data(tenant, module_id, actor_id=actor.id)
    record_platform(actor, "tenant.module_data_removed", target=slug, detail={"module": module_id})
    return queries.tenant_view(tenant)


def sync_modules(actor) -> list[str]:
    order = lifecycle.sync_catalog()
    record_platform(actor, "modules.synced", detail={"modules": order})
    return order


def upgrade_modules(actor) -> list[str]:
    order = lifecycle.upgrade_modules()
    record_platform(actor, "modules.upgraded", detail={"modules": order})
    return order


# --- admins -----------------------------------------------------------------


def add_admin(actor, data: AdminIn) -> AdminOut:
    user = User.objects.filter(email=data.email.lower()).first()
    if user is None:
        if not data.password or len(data.password) < 10:
            raise WeakPassword("a new platform admin needs a password of at least 10 characters")
        user = User.objects.create_user(
            email=data.email, password=data.password, name=data.name or "", is_platform_admin=True
        )
    else:
        if data.password:
            user.set_password(data.password)
        user.is_platform_admin = True
        user.save(
            update_fields=["is_platform_admin", "password"]
            if data.password
            else ["is_platform_admin"]
        )
    record_platform(actor, "admin.added", target=user.email)
    return queries.admin_view(user)


def remove_admin(actor, admin_id: str) -> None:
    if str(actor.id) == admin_id:
        raise DomainError("you cannot remove yourself", 409)
    with transaction.atomic():
        # Lock the admin set so concurrent removals can't both pass the count check.
        admins = list(
            User.objects.select_for_update().filter(is_platform_admin=True, is_active=True)
        )
        user = next((u for u in admins if str(u.id) == admin_id), None)
        if user is None:
            raise DomainError("platform admin not found", 404)
        if len(admins) <= 1:
            raise DomainError("cannot remove the last platform admin", 409)
        user.is_platform_admin = False
        user.save(update_fields=["is_platform_admin"])
    record_platform(actor, "admin.removed", target=user.email)
