from django.test import Client


def test_timesheets_router_is_mounted():
    from easybiz.core.api import api

    prefixes = [prefix for prefix, _ in api._routers]
    assert any("timesheets" in p for p in prefixes)


def test_mounted_module_route_is_gated_for_non_enabling_tenant(synced, provision):
    # The router is mounted install-wide; a tenant without the module must still get 404.
    provision(slug="nots", modules=())
    r = Client().get("/api/timesheets/projects", HTTP_HOST="nots.localhost")
    assert r.status_code == 404
