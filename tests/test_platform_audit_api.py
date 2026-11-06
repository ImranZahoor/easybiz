from tests.test_platform_auth_api import plat_get, plat_post
from tests.test_platform_tenants_write import _cleanup, _create


def test_audit_list_order_and_filters(admin, synced, request):
    _, token = admin
    _cleanup(request, "neo", emails=["owner@neo.test"])
    _create(token, "neo")
    plat_post("/api/platform/tenants/neo/suspend", token)

    rows = plat_get("/api/platform/audit", token).json()
    actions = [r["action"] for r in rows]
    # newest first: the suspend happened after the create
    assert actions.index("tenant.suspended") < actions.index("tenant.created")
    assert all(r["actor_email"] == "admin@platform.test" for r in rows[:2])

    # filter by action and by target
    only = plat_get("/api/platform/audit?action=tenant.suspended&target=neo", token).json()
    assert only and all(r["action"] == "tenant.suspended" and r["target"] == "neo" for r in only)

    assert len(plat_get("/api/platform/audit?limit=1", token).json()) == 1
