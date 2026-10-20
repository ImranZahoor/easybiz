from django_tenants.routers import TenantSyncRouter


class ModuleAwareTenantSyncRouter(TenantSyncRouter):
    """Module-table gating is added in M3; inherits default behaviour at M0."""
