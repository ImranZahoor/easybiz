from django.test import Client

ORIGIN = "http://acme.localhost:5173"


def test_preflight_answered_for_tenant_host(synced, provision):
    provision(slug="acme", modules=())
    r = Client().options(
        "/api/auth/login",
        HTTP_HOST="acme.localhost",
        HTTP_ORIGIN=ORIGIN,
        HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST",
    )
    assert r.status_code in (200, 204)
    assert r["Access-Control-Allow-Origin"] == ORIGIN


def test_preflight_needs_no_module_or_token(synced, provision):
    provision(slug="acme", modules=())  # timesheets NOT enabled, and no token sent
    r = Client().options(
        "/api/timesheets/entries",
        HTTP_HOST="acme.localhost",
        HTTP_ORIGIN=ORIGIN,
        HTTP_ACCESS_CONTROL_REQUEST_METHOD="GET",
    )
    assert r.status_code in (200, 204) and "Access-Control-Allow-Origin" in r


def test_error_response_carries_cors_headers(synced, provision):
    provision(slug="acme", modules=())
    r = Client().get(
        "/api/auth/me", HTTP_HOST="acme.localhost", HTTP_ORIGIN=ORIGIN
    )  # 401, no token
    assert r.status_code == 401 and r["Access-Control-Allow-Origin"] == ORIGIN


def test_subdomain_allowed_unknown_origin_not(synced, provision):
    provision(slug="acme", modules=())
    good = Client().get("/api/auth/me", HTTP_HOST="acme.localhost", HTTP_ORIGIN=ORIGIN)
    assert good["Access-Control-Allow-Origin"] == ORIGIN
    bad = Client().get(
        "/api/auth/me", HTTP_HOST="acme.localhost", HTTP_ORIGIN="http://evil.example"
    )
    assert "Access-Control-Allow-Origin" not in bad
