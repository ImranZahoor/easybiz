from django.test import Client

from tests.test_core_modules_api import _token


def test_create_and_list_role(synced, provision):
    token = _token(provision)
    c = Client()
    resp = c.post(
        "/api/core/roles",
        data={"name": "reader", "permissions": ["core.module.read"]},
        content_type="application/json",
        HTTP_HOST="acme.localhost",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    assert resp.status_code == 201
    names = [
        r["name"]
        for r in c.get(
            "/api/core/roles", HTTP_HOST="acme.localhost", HTTP_AUTHORIZATION=f"Bearer {token}"
        ).json()
    ]
    assert "reader" in names and "owner" in names


def test_create_role_star_rejected(synced, provision):
    token = _token(provision)
    resp = Client().post(
        "/api/core/roles",
        data={"name": "x", "permissions": ["*"]},
        content_type="application/json",
        HTTP_HOST="acme.localhost",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    assert resp.status_code == 422
