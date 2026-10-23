"""All-or-nothing tenant provisioning (I14)."""

from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID

from django.db import connection, transaction
from django_tenants.utils import tenant_context

from easybiz.core.audit.models import AuditLog
from easybiz.core.iam.models import Role, RolePermission, UserRole
from easybiz.core.kernel import lifecycle
from easybiz.core.kernel.registry import registry
from easybiz.core.kernel.tenants import schema_name_for, validate_new_tenant
from easybiz.core.tenancy.models import Domain, Tenant
from easybiz.core.users.models import Membership, User


def provision_tenant(
    name: str,
    slug: str,
    domain: str,
    owner_email: str,
    owner_password: str | None = None,
    modules: Iterable[str] = (),
    actor_id: UUID | None = None,
) -> Tenant:
    """Create a tenant end to end, or roll everything back on any failure (I14)."""
    domain_norm = validate_new_tenant(
        slug=slug,
        domain=domain,
        owner_email=owner_email,
        owner_password=owner_password,
        modules=modules,
    )
    schema = schema_name_for(slug)
    tenant: Tenant | None = None
    try:
        tenant = Tenant(schema_name=schema, slug=slug, name=name)
        tenant.save()  # creates the schema and migrates core tenant apps
        Domain.objects.create(domain=domain_norm, tenant=tenant, is_primary=True)

        owner = User.objects.filter(email=owner_email.lower()).first()
        if owner is None:
            owner = User.objects.create_user(email=owner_email, password=owner_password)
        Membership.objects.get_or_create(user=owner, tenant=tenant, defaults={"is_active": True})

        with tenant_context(tenant), transaction.atomic():
            role, _ = Role.objects.get_or_create(
                name="owner", defaults={"description": "Tenant owner", "is_system": True}
            )
            RolePermission.objects.get_or_create(role=role, permission="*")
            UserRole.objects.get_or_create(user_id=owner.id, role=role)
            AuditLog.objects.create(
                actor_id=actor_id, action="tenant.provisioned", entity="tenant", entity_id=slug
            )

        requested = set(modules)
        for module_id in [m for m in registry.load_order() if m in requested]:
            lifecycle.enable_module(tenant, module_id, actor_id=actor_id)
        return tenant
    except Exception:
        connection.set_schema_to_public()  # type: ignore[attr-defined]  # django-tenants method
        with connection.cursor() as cur:
            cur.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        if tenant is not None and tenant.pk:
            Tenant.objects.filter(pk=tenant.pk).delete()
        raise
