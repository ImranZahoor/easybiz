from django.test import Client
from django_tenants.utils import tenant_context

from easybiz.core.api.security import encode_tenant_token
from easybiz.core.iam import service as iam
from easybiz.core.users import service as users


def _owner_token(provision, slug):
    provision(slug=slug, modules=("timesheets",))
    return (
        Client()
        .post(
            "/api/auth/login",
            data={"email": f"owner@{slug}.test", "password": "change-me-now"},
            content_type="application/json",
            HTTP_HOST=f"{slug}.localhost",
        )
        .json()["access_token"]
    )


def test_context_returns_tenant_and_enabled_modules(synced, provision):
    token = _owner_token(provision, "ctx1")
    r = Client().get(
        "/api/core/context", HTTP_HOST="ctx1.localhost", HTTP_AUTHORIZATION=f"Bearer {token}"
    )
    assert r.status_code == 200
    body = r.json()
    assert body["tenant"]["slug"] == "ctx1"
    assert "timesheets" in body["enabled_modules"]


def test_context_open_to_any_authenticated_user(synced, provision):
    # A plain member (no core.module.read) can still read context — unlike /core/modules.
    tenant = provision(slug="ctx2", modules=("timesheets",))
    with tenant_context(tenant):
        member = users.create_user("member@ctx2.test", tenant, password="change-me-now")
        iam.set_user_roles(member.id, ["timesheet_user"])
        token = encode_tenant_token(member.id, tenant.schema_name)
    r = Client().get(
        "/api/core/context", HTTP_HOST="ctx2.localhost", HTTP_AUTHORIZATION=f"Bearer {token}"
    )
    assert r.status_code == 200 and "timesheets" in r.json()["enabled_modules"]


def test_me_no_longer_exposes_enabled_modules(synced, provision):
    token = _owner_token(provision, "ctx3")
    me = (
        Client()
        .get("/api/auth/me", HTTP_HOST="ctx3.localhost", HTTP_AUTHORIZATION=f"Bearer {token}")
        .json()
    )
    assert "enabled_modules" not in me  # moved to /api/core/context
    assert "permissions" in me and "menu" in me
