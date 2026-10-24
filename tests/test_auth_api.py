from django.test import Client


def _login(host, email, password):
    return Client().post(
        "/api/auth/login",
        data={"email": email, "password": password},
        content_type="application/json",
        HTTP_HOST=host,
    )


def test_login_and_me(synced, provision):
    provision(slug="acme")
    resp = _login("acme.localhost", "owner@acme.test", "change-me-now")
    assert resp.status_code == 200
    token = resp.json()["access_token"]
    me = Client().get(
        "/api/auth/me", HTTP_HOST="acme.localhost", HTTP_AUTHORIZATION=f"Bearer {token}"
    )
    assert me.status_code == 200
    body = me.json()
    assert body["email"] == "owner@acme.test"
    assert "*" in body["permissions"]  # owner role


def test_uniform_login_failure(synced, provision):
    provision(slug="acme")
    for email, pw in [("owner@acme.test", "wrong"), ("nobody@acme.test", "change-me-now")]:
        resp = _login("acme.localhost", email, pw)
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Invalid credentials"


def test_token_rejected_by_other_tenant(synced, provision):
    provision(slug="acme")
    provision(slug="zenith")
    token = _login("acme.localhost", "owner@acme.test", "change-me-now").json()["access_token"]
    me = Client().get(
        "/api/auth/me", HTTP_HOST="zenith.localhost", HTTP_AUTHORIZATION=f"Bearer {token}"
    )
    assert me.status_code == 401


def test_tenant_api_absent_on_public_host(synced):
    # the public host serves urls_public (health only); /api/* is not mounted there
    assert Client().get("/api/auth/me", HTTP_HOST="localhost").status_code == 404


def test_docs_render_on_tenant_host(synced, provision):
    provision(slug="acme")
    assert Client().get("/api/docs", HTTP_HOST="acme.localhost").status_code == 200
