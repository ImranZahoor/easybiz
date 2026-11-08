from django.db import connection
from django.test import Client

from tests.test_platform_auth_api import plat_delete, plat_get, plat_post


def _cleanup(request, *slugs, emails=()):
    def drop():
        from easybiz.core.tenancy.models import Tenant
        from easybiz.core.users.models import User

        connection.set_schema_to_public()
        for s in slugs:
            with connection.cursor() as cur:
                cur.execute(f'DROP SCHEMA IF EXISTS "t_{s}" CASCADE')
            Tenant.objects.filter(slug=s).delete()
        for e in emails:
            User.objects.filter(email=e).delete()

    request.addfinalizer(drop)


def _schema_exists(name):
    with connection.cursor() as cur:
        cur.execute("SELECT 1 FROM information_schema.schemata WHERE schema_name=%s", [name])
        return cur.fetchone() is not None


def _tenant_login(slug, email, password="change-me-now"):
    return Client().post(
        "/api/auth/login",
        data={"email": email, "password": password},
        content_type="application/json",
        HTTP_HOST=f"{slug}.localhost",
    )


def _create(token, slug, **over):
    body = {
        "name": slug.title(),
        "slug": slug,
        "domain": f"{slug}.localhost",
        "owner_email": f"owner@{slug}.test",
        "owner_password": "change-me-now",
        "modules": [],
    }
    body.update(over)
    return plat_post("/api/platform/tenants", token, body)


def test_create_tenant_end_to_end(admin, synced, request):
    _, token = admin
    _cleanup(request, "neo", emails=["owner@neo.test"])
    r = _create(token, "neo", modules=["timesheets"])
    assert r.status_code == 201
    assert "timesheets" in {m["module"] for m in r.json()["modules"]}
    assert _tenant_login("neo", "owner@neo.test").status_code == 200

    from easybiz.core.tenancy.models import PlatformAuditLog

    assert PlatformAuditLog.objects.filter(action="tenant.created", target="neo").exists()


def test_create_conflicts_and_validation(admin, synced, provision, request):
    _, token = admin
    provision(slug="acme", modules=())  # existing tenant (auto-cleaned)
    _cleanup(request, "neo", emails=["owner@neo.test"])
    assert _create(token, "acme").status_code == 409  # slug taken
    assert _create(token, "neo", domain="acme.localhost").status_code == 409  # domain taken
    assert _create(token, "Bad Slug").status_code == 422
    assert _create(token, "api").status_code == 422  # reserved
    assert _create(token, "neo", domain="http://neo.localhost").status_code == 422  # bad domain
    assert _create(token, "neo", owner_email="x@neo.test", owner_password=None).status_code == 422
    assert _create(token, "neo", owner_password="short").status_code == 422
    # unknown module -> 422 and nothing created
    assert _create(token, "neo", modules=["ghost"]).status_code == 422
    from easybiz.core.tenancy.models import Tenant

    assert not Tenant.objects.filter(slug="neo").exists()


def test_existing_person_owns_another_tenant_without_password(admin, synced, request):
    _, token = admin
    _cleanup(request, "one", "two", emails=["shared@x.test"])
    assert _create(token, "one", owner_email="shared@x.test").status_code == 201
    assert (
        _create(token, "two", owner_email="shared@x.test", owner_password=None).status_code == 201
    )


def test_create_rolls_back_on_failure(admin, synced, request, monkeypatch):
    _, token = admin
    _cleanup(request, "rbk", emails=["owner@rbk.test"])

    def boom(*a, **k):
        raise RuntimeError("enable failed")

    monkeypatch.setattr("easybiz.core.kernel.lifecycle.enable_module", boom)
    r = _create(token, "rbk", modules=["timesheets"])
    assert r.status_code >= 500
    from easybiz.core.tenancy.models import Tenant

    assert not Tenant.objects.filter(slug="rbk").exists()  # row gone
    assert not _schema_exists("t_rbk")  # schema dropped (I14)


def test_rename(admin, synced, request):
    _, token = admin
    _cleanup(request, "neo", emails=["owner@neo.test"])
    _create(token, "neo")
    r = Client().patch(
        "/api/platform/tenants/neo",
        data={"name": "Neo Corp"},
        content_type="application/json",
        HTTP_HOST="localhost",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    assert r.status_code == 200 and r.json()["name"] == "Neo Corp"


def test_suspend_blocks_then_resume_restores(admin, synced, request):
    _, token = admin
    _cleanup(request, "neo", emails=["owner@neo.test"])
    _create(token, "neo")
    tok = _tenant_login("neo", "owner@neo.test").json()["access_token"]

    assert plat_post("/api/platform/tenants/neo/suspend", token).status_code == 200
    assert _tenant_login("neo", "owner@neo.test").status_code == 403  # login blocked
    me = Client().get("/api/auth/me", HTTP_HOST="neo.localhost", HTTP_AUTHORIZATION=f"Bearer {tok}")
    assert me.status_code == 403  # old token blocked
    assert Client().get("/api/docs", HTTP_HOST="neo.localhost").status_code == 403  # docs blocked
    assert plat_post("/api/platform/tenants/neo/suspend", token).status_code == 409  # already

    assert plat_post("/api/platform/tenants/neo/resume", token).status_code == 200
    assert _tenant_login("neo", "owner@neo.test").status_code == 200  # restored
    assert plat_post("/api/platform/tenants/neo/resume", token).status_code == 409  # already active


def test_delete_requires_suspension_and_confirmation(admin, synced, request):
    _, token = admin
    _cleanup(request, "neo", emails=["owner@neo.test"])
    _create(token, "neo")
    assert (
        plat_delete("/api/platform/tenants/neo?confirm_slug=neo", token).status_code == 409
    )  # not suspended
    plat_post("/api/platform/tenants/neo/suspend", token)
    assert plat_delete("/api/platform/tenants/neo?confirm_slug=wrong", token).status_code == 422
    assert plat_delete("/api/platform/tenants/neo", token).status_code == 422  # missing confirm
    assert plat_delete("/api/platform/tenants/neo?confirm_slug=neo", token).status_code == 204

    from easybiz.core.users.models import User

    assert not _schema_exists("t_neo")  # schema dropped
    assert plat_get("/api/platform/tenants/neo", token).status_code == 404  # tenant gone
    assert User.objects.filter(email="owner@neo.test").exists()  # people kept
