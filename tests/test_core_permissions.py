from easybiz.core.catalog.models import Permission
from easybiz.core.kernel import lifecycle


def test_sync_catalog_upserts_core_permissions(synced):
    lifecycle.sync_catalog()
    codes = set(Permission.objects.filter(module__isnull=True).values_list("code", flat=True))
    assert {
        "core.module.read",
        "core.module.manage",
        "core.role.read",
        "core.role.manage",
        "core.user.read",
        "core.user.manage",
        "core.audit.read",
    } <= codes
