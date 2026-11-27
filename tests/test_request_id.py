from django.test import Client


def _login(provision, slug, **extra):
    provision(slug=slug, modules=())
    return Client().post(
        "/api/auth/login",
        data={"email": f"owner@{slug}.test", "password": "change-me-now"},
        content_type="application/json",
        HTTP_HOST=f"{slug}.localhost",
        **extra,
    )


def test_request_id_header_on_success(synced, provision):
    r = _login(provision, "r1")
    assert r.status_code == 200 and r["X-Request-ID"]


def test_incoming_request_id_is_echoed(synced, provision):
    r = _login(provision, "r2", HTTP_X_REQUEST_ID="client-abc_123")
    assert r["X-Request-ID"] == "client-abc_123"


def test_hostile_incoming_request_id_is_replaced(synced, provision):
    bad = "x" * 200 + "\r\nInjected: 1"  # oversized + CRLF injection attempt
    r = _login(provision, "r3", HTTP_X_REQUEST_ID=bad)
    assert r["X-Request-ID"] != bad and "\n" not in r["X-Request-ID"]


def test_error_body_carries_request_id(synced, provision):
    provision(slug="r4", modules=())
    r = Client().get("/api/tools", HTTP_HOST="r4.localhost")  # 401, enveloped
    assert r.status_code == 401
    assert r.json()["request_id"] and r.json()["request_id"] == r["X-Request-ID"]


def test_module_not_enabled_is_enveloped(synced, provision):
    provision(slug="r5", modules=())  # timesheets installed but NOT enabled
    r = Client().get("/api/timesheets/projects", HTTP_HOST="r5.localhost")
    assert r.status_code == 404
    body = r.json()
    assert body["code"] == "module.not_enabled" and body["request_id"] and body["errors"] == []


def test_tenant_suspended_is_enveloped(synced, provision):
    from easybiz.core.tenancy.models import Tenant

    provision(slug="r6", modules=())
    Tenant.objects.filter(slug="r6").update(is_active=False)
    r = Client().get("/api/tools", HTTP_HOST="r6.localhost")
    assert r.status_code == 403
    assert r.json()["code"] == "tenant.suspended" and r.json()["request_id"]
