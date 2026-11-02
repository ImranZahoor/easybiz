from django.test import Client

from easybiz.core.kernel import tenants


def test_disabled_module_route_is_gated(synced, provision):
    provision(slug="acme")  # demo installed, not enabled
    resp = Client().get("/api/demo/widgets", HTTP_HOST="acme.localhost")
    assert resp.status_code == 404
    assert "not enabled" in resp.json()["detail"]


def test_disabled_module_without_trailing_slash_gated(synced, provision):
    provision(slug="acme")
    resp = Client().get("/api/demo", HTTP_HOST="acme.localhost")
    assert resp.status_code == 404
    assert "not enabled" in resp.json()["detail"]


def test_non_module_path_not_gated(synced, provision):
    provision(slug="acme")
    # /api/auth/* is not a module segment -> reaches the endpoint (401, not the gate's 404)
    assert Client().get("/api/auth/me", HTTP_HOST="acme.localhost").status_code == 401


def test_suspended_tenant_is_forbidden(synced, provision):
    tenant = provision(slug="acme")
    tenants.suspend(tenant)
    resp = Client().get("/api/auth/me", HTTP_HOST="acme.localhost")
    assert resp.status_code == 403
    assert "suspended" in resp.json()["detail"]
