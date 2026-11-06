from tests.test_platform_auth_api import plat_get


def test_list_excludes_platform_tenant_and_paginates(admin, synced, provision):
    _, token = admin
    provision(slug="acme", modules=("timesheets",))
    provision(slug="zenith", modules=())
    body = plat_get("/api/platform/tenants", token).json()
    slugs = [t["slug"] for t in body["items"]]
    assert "acme" in slugs and "zenith" in slugs and "platform" not in slugs
    assert body["count"] >= 2

    page = plat_get("/api/platform/tenants?limit=1&offset=0", token).json()
    assert len(page["items"]) == 1 and page["count"] >= 2


def test_search_and_filter(admin, synced, provision):
    _, token = admin
    provision(slug="acme", modules=())
    zen = provision(slug="zenith", modules=())
    from easybiz.core.kernel import tenants as tops

    tops.suspend(zen)
    assert [t["slug"] for t in plat_get("/api/platform/tenants?q=zen", token).json()["items"]] == [
        "zenith"
    ]
    actives = plat_get("/api/platform/tenants?is_active=true", token).json()["items"]
    assert "zenith" not in [t["slug"] for t in actives] and "acme" in [t["slug"] for t in actives]


def test_detail_shape(admin, synced, provision):
    _, token = admin
    provision(slug="acme", modules=("timesheets",))
    t = plat_get("/api/platform/tenants/acme", token).json()
    assert t["slug"] == "acme" and t["schema_name"] == "t_acme" and t["is_active"] is True
    assert {"timesheets"} <= {m["module"] for m in t["modules"]}
    assert any(d["is_primary"] for d in t["domains"]) and t["member_count"] >= 1


def test_detail_unknown_slug_404(admin):
    _, token = admin
    assert plat_get("/api/platform/tenants/ghost", token).status_code == 404


def test_overview_counts(admin, synced, provision):
    _, token = admin
    provision(slug="acme", modules=("timesheets",))
    o = plat_get("/api/platform/overview", token).json()
    assert o["tenants_total"] >= 1 and o["tenants_active"] >= 1
    assert o["platform_admins"] >= 1 and o["modules_installed"] >= 1
