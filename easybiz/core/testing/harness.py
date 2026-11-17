from __future__ import annotations

import contextlib
import uuid
from collections.abc import Iterable, Iterator

from django.db import connection

from easybiz.core.kernel import provisioning
from easybiz.core.kernel.registry import registry
from easybiz.core.tenancy.models import Tenant
from easybiz.core.users.models import User


def _deps_closure(module_id: str) -> set[str]:
    """Every module in ``module_id``'s transitive `requires` chain (hard deps)."""
    seen: set[str] = set()

    def visit(mid: str) -> None:
        manifest = registry.manifest(mid)
        for dep, _ in manifest.requires if manifest else []:
            if dep not in seen:
                seen.add(dep)
                visit(dep)

    visit(module_id)
    return seen


@contextlib.contextmanager
def module_harness(
    module_id: str, with_: Iterable[str] = (), without: Iterable[str] = ()
) -> Iterator[Tenant]:
    """Provision a throwaway tenant with ``module_id`` + hard deps (+with_, -without), then drop it."""
    mods = ({module_id} | _deps_closure(module_id) | set(with_)) - set(without)
    slug = f"ct{module_id.replace('_', '')}{uuid.uuid4().hex[:6]}"
    email = f"owner@{slug}.test"
    connection.set_schema_to_public()  # type: ignore[attr-defined]  # provisioning needs public
    tenant = provisioning.provision_tenant(
        name=slug,
        slug=slug,
        domain=f"{slug}.localhost",
        owner_email=email,
        owner_password="change-me-now",
        modules=sorted(mods),
    )
    try:
        yield tenant
    finally:
        connection.set_schema_to_public()  # type: ignore[attr-defined]  # django-tenants
        with connection.cursor() as cur:
            cur.execute(f'DROP SCHEMA IF EXISTS "{tenant.schema_name}" CASCADE')
        Tenant.objects.filter(schema_name=tenant.schema_name).delete()
        User.objects.filter(email=email).delete()
