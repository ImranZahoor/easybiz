from django.test import Client

from easybiz.core.api import envelope
from easybiz.core.errors import DomainError


def test_build_shape_and_default_code():
    out = envelope.build("nope", 403, request_id="rid1")
    assert out == {"detail": "nope", "code": "auth.forbidden", "errors": [], "request_id": "rid1"}


def test_build_explicit_code_and_errors():
    out = envelope.build(
        "bad",
        422,
        code="validation.failed",
        errors=[{"field": "hours", "code": "range", "message": "too big"}],
    )
    assert out["code"] == "validation.failed" and out["errors"][0]["field"] == "hours"


def test_domain_error_carries_optional_code():
    assert DomainError("x", 404).code is None  # falls back to the status default at build time
    assert DomainError("x", 404, "module.not_enabled").code == "module.not_enabled"


def _login_owner(provision, slug):
    provision(slug=slug, modules=())
    return Client().post(
        "/api/auth/login",
        data={"email": f"owner@{slug}.test", "password": "change-me-now"},
        content_type="application/json",
        HTTP_HOST=f"{slug}.localhost",
    )


def test_401_is_enveloped(synced, provision):
    provision(slug="e1", modules=())
    r = Client().get("/api/tools", HTTP_HOST="e1.localhost")  # authed endpoint, no credentials
    assert r.status_code == 401
    body = r.json()
    assert body["code"] == "auth.token_invalid" and body["errors"] == [] and "request_id" in body


def test_422_body_validation_has_field_errors(synced, provision):
    provision(slug="e2", modules=())
    r = Client().post(
        "/api/auth/login",
        data={},
        content_type="application/json",
        HTTP_HOST="e2.localhost",
    )  # missing email/password → ninja ValidationError
    assert r.status_code == 422
    body = r.json()
    assert body["code"] == "validation.failed"
    assert body["errors"] and all({"field", "code", "message"} <= set(e) for e in body["errors"])


def test_domain_error_is_enveloped(synced, provision):
    # a DomainError (RoleError, 422) flows through the DomainError handler → envelope, errors [].
    token = _login_owner(provision, "e3").json()["access_token"]
    hdr = {"HTTP_HOST": "e3.localhost", "HTTP_AUTHORIZATION": f"Bearer {token}"}
    body = {"name": "dup-role", "description": "", "permissions": []}
    Client().post("/api/core/roles", data=body, content_type="application/json", **hdr)
    r = Client().post("/api/core/roles", data=body, content_type="application/json", **hdr)
    assert r.status_code == 422  # duplicate name
    out = r.json()
    assert out["code"] == "validation.failed" and out["errors"] == [] and "request_id" in out


def test_http_error_invalid_credentials_is_enveloped(synced, provision):
    # the bad-password login raises ninja HttpError(401) — must flow through the envelope too
    provision(slug="e4", modules=())
    r = Client().post(
        "/api/auth/login",
        data={"email": "owner@e4.test", "password": "wrong-password"},
        content_type="application/json",
        HTTP_HOST="e4.localhost",
    )
    assert r.status_code == 401
    body = r.json()
    assert body["code"] == "auth.token_invalid" and body["errors"] == [] and "request_id" in body


def test_platform_plane_error_is_enveloped(synced):
    # a platform-plane bad login (HttpError 401) carries the envelope on the platform api too
    r = Client().post(
        "/api/platform/auth/login",
        data={"email": "nobody@example.com", "password": "nope"},
        content_type="application/json",
        HTTP_HOST="localhost",
    )
    assert r.status_code == 401
    body = r.json()
    assert {"detail", "code", "errors", "request_id"} <= set(body) and body["code"]
