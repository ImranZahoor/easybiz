from django.test import Client
from django_tenants.utils import tenant_context

from easybiz.core.api.security import encode_tenant_token
from easybiz.core.iam import service as iam
from easybiz.core.iam.models import UserRole
from easybiz.core.tenancy.models import Tenant
from easybiz.core.users import service as users


def _owner(provision, slug):
    provision(slug=slug, modules=())
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


def _limited_token(tenant, perms):
    with tenant_context(tenant):
        role = iam.create_role(tenant, "limited", perms, "")
        u = users.create_user("limited@x.test", tenant, password="change-me-now")
        UserRole.objects.create(user_id=u.id, role=role)
        return encode_tenant_token(u.id, tenant.schema_name)


def _req(method, path, token, slug, body=None):
    kw = {"HTTP_HOST": f"{slug}.localhost", "HTTP_AUTHORIZATION": f"Bearer {token}"}
    if body is not None:
        kw["data"] = body
        kw["content_type"] = "application/json"
    return getattr(Client(), method)(path, **kw)


def test_requires_apikey_manage(synced, provision):
    _owner(provision, "ak1")
    tok = _limited_token(Tenant.objects.get(slug="ak1"), ["core.user.read"])
    assert _req("get", "/api/core/apikeys", tok, "ak1").status_code == 403


def test_create_returns_secret_then_list_hides_it(synced, provision):
    token = _owner(provision, "ak2")
    r = _req(
        "post",
        "/api/core/apikeys",
        token,
        "ak2",
        {"name": "ci", "permissions": ["core.audit.read"]},
    )
    assert r.status_code == 201 and "." in r.json()["secret"]
    listed = _req("get", "/api/core/apikeys", token, "ak2").json()
    assert listed and "secret" not in listed[0]


def test_subset_rule_422(synced, provision):
    _owner(provision, "ak3")
    tok = _limited_token(Tenant.objects.get(slug="ak3"), ["core.apikey.manage"])
    r = _req(
        "post",
        "/api/core/apikeys",
        tok,
        "ak3",
        {"name": "x", "permissions": ["core.user.manage"]},
    )
    assert r.status_code == 422


def test_revoke(synced, provision):
    token = _owner(provision, "ak4")
    kid = _req("post", "/api/core/apikeys", token, "ak4", {"name": "ci"}).json()["id"]
    assert _req("delete", f"/api/core/apikeys/{kid}", token, "ak4").status_code == 204
