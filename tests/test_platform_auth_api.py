from django.conf import settings
from django.test import Client


def plat_get(path, token):
    return Client().get(path, HTTP_HOST="localhost", HTTP_AUTHORIZATION=f"Bearer {token}")


def plat_post(path, token, body=None):
    return Client().post(
        path,
        data=body or {},
        content_type="application/json",
        HTTP_HOST="localhost",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )


def plat_delete(path, token):
    return Client().delete(path, HTTP_HOST="localhost", HTTP_AUTHORIZATION=f"Bearer {token}")


def _login(email, password):
    return Client().post(
        "/api/platform/auth/login",
        data={"email": email, "password": password},
        content_type="application/json",
        HTTP_HOST="localhost",
    )


def test_login_returns_token(admin):
    user, _ = admin
    r = _login("admin@platform.test", "change-me-now")
    assert r.status_code == 200 and r.json()["access_token"]


def test_bad_credentials_401(admin):
    assert _login("admin@platform.test", "wrong").status_code == 401


def test_missing_token_401():
    assert Client().get("/api/platform/me", HTTP_HOST="localhost").status_code == 401


def test_tenant_owner_is_not_platform_admin(synced, provision):
    provision(slug="acme", modules=())
    assert _login("owner@acme.test", "change-me-now").status_code == 401


def test_tokens_not_interchangeable(admin, synced, provision):
    _, plat_token = admin
    provision(slug="acme", modules=())
    tenant_token = (
        Client()
        .post(
            "/api/auth/login",
            data={"email": "owner@acme.test", "password": "change-me-now"},
            content_type="application/json",
            HTTP_HOST="acme.localhost",
        )
        .json()["access_token"]
    )
    # tenant token rejected by the platform API; platform token rejected by the tenant API
    assert plat_get("/api/platform/me", tenant_token).status_code == 401
    assert (
        Client()
        .get("/api/auth/me", HTTP_HOST="acme.localhost", HTTP_AUTHORIZATION=f"Bearer {plat_token}")
        .status_code
        == 401
    )


def test_platform_api_absent_on_tenant_host(admin, synced, provision):
    _, token = admin
    provision(slug="acme", modules=())
    r = Client().get(
        "/api/platform/me", HTTP_HOST="acme.localhost", HTTP_AUTHORIZATION=f"Bearer {token}"
    )
    assert r.status_code == 404


def test_login_rate_limited_429(admin):
    limit = int(settings.EASYBIZ_PLATFORM_LOGIN_RATE.split("/")[0])
    codes = [_login("admin@platform.test", "wrong").status_code for _ in range(limit + 1)]
    assert codes[-1] == 429


def test_demoted_admin_loses_access_immediately(admin):
    from easybiz.core.users.models import User

    user, token = admin
    assert plat_get("/api/platform/me", token).status_code == 200
    User.objects.filter(id=user.id).update(is_platform_admin=False)
    assert plat_get("/api/platform/me", token).status_code == 401
