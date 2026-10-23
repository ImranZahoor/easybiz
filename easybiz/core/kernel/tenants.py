"""Tenant validation and lifecycle operations (provisioning lives in provisioning.py)."""

from __future__ import annotations

import re

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
