from tests.test_platform_auth_api import plat_delete, plat_get, plat_post
from tests.test_platform_tenants_write import _cleanup, _create


def _mods(resp):
    return {m["module"]: m["status"] for m in resp.json()["modules"]}


def test_enable_disable_remove_from_platform(admin, synced, request):
    _, token = admin
    _cleanup(request, "neo", emails=["owner@neo.test"])
    _create(token, "neo")  # no modules yet
    r = plat_post("/api/platform/tenants/neo/modules/timesheets/enable", token)
    assert r.status_code == 200 and _mods(r).get("timesheets") == "enabled"
    r = plat_post("/api/platform/tenants/neo/modules/timesheets/disable", token)
    assert _mods(r).get("timesheets") == "disabled"
    assert (
        plat_delete(
            "/api/platform/tenants/neo/modules/timesheets/data?confirm=true", token
        ).status_code
        == 200
    )

    from easybiz.core.tenancy.models import PlatformAuditLog

    actions = set(PlatformAuditLog.objects.filter(target="neo").values_list("action", flat=True))
    assert {
        "tenant.module_enabled",
        "tenant.module_disabled",
        "tenant.module_data_removed",
    } <= actions


def test_remove_without_confirm_400(admin, synced, request):
    _, token = admin
    _cleanup(request, "neo", emails=["owner@neo.test"])
    _create(token, "neo")
    plat_post("/api/platform/tenants/neo/modules/timesheets/enable", token)
    plat_post("/api/platform/tenants/neo/modules/timesheets/disable", token)
    assert (
        plat_delete("/api/platform/tenants/neo/modules/timesheets/data", token).status_code == 400
    )


def test_module_catalog_and_counts(admin, synced, request):
    _, token = admin
    _cleanup(request, "neo", emails=["owner@neo.test"])
    _create(token, "neo", modules=["timesheets"])
    entries = {m["id"]: m for m in plat_get("/api/platform/modules", token).json()}
    ts = entries["timesheets"]
    assert ts["state"] == "installed" and ts["tenants_enabled"] >= 1
    assert ts["code_version"] and "timesheets.entry.approved" in ts["publishes"]
    assert any(p["code"] == "timesheets.entry.approve" for p in ts["permissions"])
    assert plat_get("/api/platform/modules/ghost", token).status_code == 404


def test_sync_and_upgrade(admin, synced):
    _, token = admin
    s = plat_post("/api/platform/modules/sync", token)
    assert s.status_code == 200 and "timesheets" in s.json()["modules"]
    u = plat_post("/api/platform/modules/upgrade", token)
    assert u.status_code == 200 and "timesheets" in u.json()["modules"]

    from easybiz.core.tenancy.models import PlatformAuditLog

    assert PlatformAuditLog.objects.filter(action="modules.synced").exists()
    assert PlatformAuditLog.objects.filter(action="modules.upgraded").exists()


def test_fixed_module_route_resolves_before_param(admin, synced):
    # POST /modules/sync must hit sync (ModulesOut), not get_module(id="sync") — pitfall P8.
    _, token = admin
    r = plat_post("/api/platform/modules/sync", token)
    assert r.status_code == 200 and "modules" in r.json()
