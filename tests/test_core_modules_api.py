from django.test import Client


def _token(provision, slug="acme"):
    provision(slug=slug)
    r = Client().post(
        "/api/auth/login",
        data={"email": f"owner@{slug}.test", "password": "change-me-now"},
        content_type="application/json",
        HTTP_HOST=f"{slug}.localhost",
    )
    return r.json()["access_token"]


def _get(path, token, slug="acme"):
    return Client().get(path, HTTP_HOST=f"{slug}.localhost", HTTP_AUTHORIZATION=f"Bearer {token}")


def _post(path, token, slug="acme"):
    return Client().post(path, HTTP_HOST=f"{slug}.localhost", HTTP_AUTHORIZATION=f"Bearer {token}")


def test_list_and_enable_disable_module(synced, provision):
    token = _token(provision)  # owner has '*'
    listing = _get("/api/core/modules", token).json()
    demo = next(m for m in listing if m["id"] == "demo")
    assert demo["status"] == "available"

    assert _post("/api/core/modules/demo/enable", token).json()["status"] == "enabled"
    assert _post("/api/core/modules/demo/disable", token).json()["status"] == "disabled"
    assert _post("/api/core/modules/demo/enable", token).status_code == 200


def test_enable_twice_409(synced, provision):
    token = _token(provision)
    _post("/api/core/modules/demo/enable", token)
    assert _post("/api/core/modules/demo/enable", token).status_code == 409


def test_remove_data_needs_confirm_and_disabled(synced, provision):
    token = _token(provision)
    _post("/api/core/modules/demo/enable", token)
    no_confirm = Client().delete(
        "/api/core/modules/demo/data",
        HTTP_HOST="acme.localhost",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    assert no_confirm.status_code == 400
    _post("/api/core/modules/demo/disable", token)
    ok = Client().delete(
        "/api/core/modules/demo/data?confirm=true",
        HTTP_HOST="acme.localhost",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    assert ok.status_code == 200
