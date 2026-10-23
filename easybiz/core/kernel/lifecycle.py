"""Per-tenant module lifecycle: install, enable, disable, remove, upgrade."""

from __future__ import annotations

from contextlib import contextmanager

from django.core.management import call_command
from django.db import connection, transaction
from django.utils import timezone
from django_tenants.utils import get_public_schema_name, tenant_context

from easybiz.core.audit.models import AuditLog
from easybiz.core.catalog.models import Module, Permission, TenantModule
from easybiz.core.events.models import OutboxEvent
from easybiz.core.iam.models import Role, RolePermission
from easybiz.core.kernel import state
from easybiz.core.kernel.manifest import Version, VersionRange
from easybiz.core.kernel.registry import registry


class LifecycleError(Exception):
    """Raised for any invalid module lifecycle transition (maps to HTTP 409)."""


@contextmanager
def _keep_connection_tenant():
    """Restore the connection's schema after a call that resets it to public (I12)."""
    previous = connection.schema_name
    try:
        yield
    finally:
        if previous == get_public_schema_name():
            connection.set_schema_to_public()
        else:
            from easybiz.core.tenancy.models import Tenant

            connection.set_tenant(Tenant.objects.get(schema_name=previous))


def install_module(module_id: str) -> None:
    manifest = registry.manifest(module_id)
    if manifest is None:
        raise LifecycleError(f"module {module_id!r} is not installed on disk")
    with transaction.atomic():
        Module.objects.update_or_create(
            id=manifest.id,
            defaults={
                "name": manifest.name,
                "version": manifest.version,
                "manifest": manifest.to_dict(),
            },
        )
        declared = {code for code, _ in manifest.permissions}
        for code, desc in manifest.permissions:
            Permission.objects.update_or_create(
                code=code, defaults={"module_id": manifest.id, "description": desc}
            )
        Permission.objects.filter(module_id=manifest.id).exclude(code__in=declared).delete()


def sync_catalog() -> list[str]:
    order = registry.load_order()
    for module_id in order:
        install_module(module_id)
    return order


def enable_module(tenant, module_id: str, actor_id=None) -> None:
    manifest = registry.manifest(module_id)
    if manifest is None or not Module.objects.filter(id=module_id).exists():
        raise LifecycleError(f"module {module_id!r} is not in the catalog")
    if state.is_enabled(tenant, module_id):
        raise LifecycleError(f"module {module_id!r} is already enabled")
    _assert_requirements_enabled(tenant, manifest)

    with _keep_connection_tenant():
        row, created = TenantModule.objects.get_or_create(
            tenant=tenant,
            module_id=module_id,
            defaults={"status": TenantModule.ENABLING, "installed_version": manifest.version},
        )
        try:
            call_command("migrate_schemas", module_id, schema_name=tenant.schema_name, verbosity=0)
        except Exception as exc:
            if created:
                row.delete()
            else:
                row.status = TenantModule.DISABLED
                row.save(update_fields=["status"])
            raise LifecycleError(f"migrations for {module_id!r} failed: {exc}") from exc

    try:
        with tenant_context(tenant), transaction.atomic():
            _seed_roles(manifest)
            requeue_parked(module_id)
            AuditLog.objects.create(
                actor_id=actor_id,
                action="module.enabled",
                entity="module",
                entity_id=module_id,
                after={"version": manifest.version},
            )
            OutboxEvent.objects.create(
                name="core.module.enabled",
                producer="core",
                payload={"module": module_id, "version": manifest.version},
            )
    except Exception as exc:
        # tables are migrated but seeding failed: leave the row DISABLED (tables
        # exist, not enabled) rather than stuck in ENABLING, and honour the
        # LifecycleError contract.
        TenantModule.objects.filter(tenant=tenant, module_id=module_id).update(
            status=TenantModule.DISABLED
        )
        raise LifecycleError(f"enabling {module_id!r} failed after migration: {exc}") from exc
    TenantModule.objects.filter(tenant=tenant, module_id=module_id).update(
        status=TenantModule.ENABLED,
        installed_version=manifest.version,
        enabled_at=timezone.now(),
    )


def disable_module(tenant, module_id: str, actor_id=None) -> None:
    if not state.is_enabled(tenant, module_id):
        raise LifecycleError(f"module {module_id!r} is not enabled")
    blockers = _enabled_dependents(tenant, module_id)
    if blockers:
        raise LifecycleError(f"cannot disable {module_id!r}; required by {sorted(blockers)}")
    TenantModule.objects.filter(tenant=tenant, module_id=module_id).update(
        status=TenantModule.DISABLED
    )
    with tenant_context(tenant), transaction.atomic():
        AuditLog.objects.create(
            actor_id=actor_id, action="module.disabled", entity="module", entity_id=module_id
        )
        OutboxEvent.objects.create(
            name="core.module.disabled", producer="core", payload={"module": module_id}
        )


def remove_module_data(tenant, module_id: str, actor_id=None, policy: str = "drop") -> None:
    if policy != "drop":
        raise LifecycleError("only policy='drop' is supported")
    row = TenantModule.objects.filter(tenant=tenant, module_id=module_id).first()
    if row is None or row.status != TenantModule.DISABLED:
        raise LifecycleError(f"module {module_id!r} must be disabled before data removal")
    if _dependents_with_row(tenant, module_id):
        raise LifecycleError(f"cannot remove {module_id!r}; dependents still hold data")
    with _keep_connection_tenant():
        call_command(
            "migrate_schemas", module_id, "zero", schema_name=tenant.schema_name, verbosity=0
        )
    manifest = registry.manifest(module_id)
    codes = {code for code, _ in manifest.permissions} if manifest else set()
    with tenant_context(tenant), transaction.atomic():
        RolePermission.objects.filter(permission__in=codes).delete()
        AuditLog.objects.create(
            actor_id=actor_id, action="module.data_removed", entity="module", entity_id=module_id
        )
    row.delete()


def upgrade_modules() -> list[str]:
    order = sync_catalog()
    call_command("migrate_schemas", verbosity=0)
    # Only enabled rows had their tables migrated to the new version.
    for row in TenantModule.objects.filter(status=TenantModule.ENABLED):
        manifest = registry.manifest(row.module_id)
        if manifest:
            TenantModule.objects.filter(pk=row.pk).update(installed_version=manifest.version)
    return order


def requeue_parked(module_id: str) -> int:
    count = 0
    for event in OutboxEvent.objects.filter(parked__contains=module_id):
        event.parked = [m for m in event.parked if m != module_id]
        event.status = OutboxEvent.PENDING
        event.next_attempt_at = timezone.now()
        event.save(update_fields=["parked", "status", "next_attempt_at"])
        count += 1
    return count


# --- helpers -----------------------------------------------------------------


def _assert_requirements_enabled(tenant, manifest) -> None:
    for dep, rng in manifest.requires:
        if not state.is_enabled(tenant, dep):
            raise LifecycleError(f"module {manifest.id!r} requires {dep!r} to be enabled first")
        dep_manifest = registry.manifest(dep)
        if dep_manifest is None:
            continue
        if not VersionRange.parse(rng).contains(Version.parse(dep_manifest.version)):
            raise LifecycleError(f"module {manifest.id!r} requires {dep!r} {rng}")


def _enabled_dependents(tenant, module_id: str) -> set[str]:
    enabled = state.enabled_module_ids(tenant)
    return {d for d in registry.dependents_of(module_id) if d in enabled}


def _dependents_with_row(tenant, module_id: str) -> set[str]:
    have_rows = set(TenantModule.objects.filter(tenant=tenant).values_list("module_id", flat=True))
    return {d for d in registry.dependents_of(module_id) if d in have_rows}


def _seed_roles(manifest) -> None:
    """Ensure each manifest role exists with its declared permissions present.

    Existing roles are not clobbered (tenant customisations kept), but the
    module's own declared permissions are (re)asserted so a
    remove-data -> re-enable cycle restores them. The overwrite policy for
    customised roles is revisited in F14.
    """
    for role in manifest.roles:
        obj, _ = Role.objects.get_or_create(
            name=role["name"],
            defaults={"description": role.get("description", ""), "is_system": False},
        )
        for perm in role.get("permissions", []):
            RolePermission.objects.get_or_create(role=obj, permission=perm)
