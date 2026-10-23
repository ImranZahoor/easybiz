"""Tenant validation and lifecycle operations (provisioning lives in provisioning.py)."""

from __future__ import annotations

import re

from django.db import connection

from easybiz.core.catalog.models import Module
from easybiz.core.kernel.registry import registry
from easybiz.core.tenancy.models import Domain, Tenant
from easybiz.core.users.models import User

_SLUG_RE = re.compile(r"^[a-z][a-z0-9-]{1,30}$")
_RESERVED_SLUGS = {"public", "platform", "admin", "api", "www"}


class TenantError(Exception):
    """Base class for tenant operation failures."""


class TenantConflict(TenantError):
    """A uniqueness/state conflict (maps to HTTP 409)."""


class TenantValidationError(TenantError):
    """Invalid input (maps to HTTP 422)."""


def schema_name_for(slug: str) -> str:
    return "t_" + slug.replace("-", "_")


def normalize_domain(domain: str) -> str:
    d = (domain or "").strip().lower()
    if not d or "://" in d or "/" in d or ":" in d or " " in d:
        raise TenantValidationError(f"invalid domain {domain!r}")
    return d


def validate_new_tenant(*, slug, domain, owner_email, owner_password, modules) -> str:
    """Validate a provisioning request, creating nothing. Returns the normalized domain."""
    if not _SLUG_RE.match(slug):
        raise TenantValidationError(f"invalid slug {slug!r}")
    if slug in _RESERVED_SLUGS:
        raise TenantValidationError(f"reserved slug {slug!r}")
    schema = schema_name_for(slug)
    if (
        Tenant.objects.filter(slug=slug).exists()
        or Tenant.objects.filter(schema_name=schema).exists()
    ):
        raise TenantConflict(f"slug {slug!r} is already in use")

    domain_norm = normalize_domain(domain)
    if Domain.objects.filter(domain=domain_norm).exists():
        raise TenantConflict(f"domain {domain_norm!r} is already in use")

    owner = User.objects.filter(email=owner_email.lower()).first()
    if owner is None and (not owner_password or len(owner_password) < 10):
        raise TenantValidationError("owner password must be at least 10 characters")

    requested = set(modules)
    for mid in requested:
        if not Module.objects.filter(id=mid).exists():
            raise TenantValidationError(f"unknown module {mid!r}")
        manifest = registry.manifest(mid)
        if manifest:
            for dep, _ in manifest.requires:
                if dep not in requested:
                    raise TenantValidationError(
                        f"module {mid!r} requires {dep!r} in the same request"
                    )
    return domain_norm


def suspend(tenant) -> None:
    if not tenant.is_active:
        raise TenantConflict("tenant is already suspended")
    tenant.is_active = False
    tenant.save(update_fields=["is_active"])


def resume(tenant) -> None:
    if tenant.is_active:
        raise TenantConflict("tenant is already active")
    tenant.is_active = True
    tenant.save(update_fields=["is_active"])


def add_domain(tenant, domain, is_primary: bool = False) -> Domain:
    d = normalize_domain(domain)
    if Domain.objects.filter(domain=d).exists():
        raise TenantConflict(f"domain {d!r} is already in use")
    return Domain.objects.create(domain=d, tenant=tenant, is_primary=is_primary)


def remove_domain(tenant, domain) -> None:
    d = normalize_domain(domain)
    row = Domain.objects.filter(tenant=tenant, domain=d).first()
    if row is None:
        raise TenantValidationError(f"{d!r} is not a domain of this tenant")
    if tenant.domains.count() <= 1:
        raise TenantConflict("a tenant must keep at least one domain")
    was_primary = row.is_primary
    row.delete()
    if was_primary:
        promoted = tenant.domains.first()
        promoted.is_primary = True
        promoted.save(update_fields=["is_primary"])


def delete_tenant(tenant, confirm_slug: str) -> None:
    if tenant.is_active:
        raise TenantConflict("tenant must be suspended before deletion")
    if confirm_slug != tenant.slug:
        raise TenantValidationError("confirm_slug does not match the tenant slug")
    schema = tenant.schema_name
    connection.set_schema_to_public()  # type: ignore[attr-defined]  # django-tenants method
    with connection.cursor() as cur:
        cur.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
    tenant.delete()  # people (users) are kept; memberships cascade
