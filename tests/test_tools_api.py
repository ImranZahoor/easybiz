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


def test_list_filtered_by_permission(synced, provision):
    token = _owner(provision, "t1")
    names = {t["name"] for t in _req("get", "/api/tools", token, "t1").json()}
    assert "core.context" in names and "core.audit.list" in names  # owner holds *


def test_describe_unknown_404(synced, provision):
    token = _owner(provision, "t2")
    assert _req("get", "/api/tools/nope", token, "t2").status_code == 404


def test_invoke_happy(synced, provision):
    token = _owner(provision, "t3")
    r = _req("post", "/api/tools/core.context/invoke", token, "t3", {})
    assert r.status_code == 200 and "enabled_modules" in r.json()


def test_describe_disabled_module_tool_404(synced, provision):
    token = _owner(provision, "t6")  # provisioned with no modules -> timesheets disabled
    r = _req("get", "/api/tools/timesheets.projects.list", token, "t6")
    assert r.status_code == 404  # disabled module -> clean 404, not a 403 leak


def test_invoke_malformed_json_422(synced, provision):
    token = _owner(provision, "t5")
    r = _req("post", "/api/tools/core.context/invoke", token, "t5", "not-json")
    assert r.status_code == 422


def test_invoke_denied_for_unscoped_user(synced, provision):
    _owner(provision, "t4")
    tenant = Tenant.objects.get(slug="t4")
    tok = _limited_token(tenant, ["core.user.read"])  # lacks core.audit.read
    assert _req("post", "/api/tools/core.audit.list/invoke", tok, "t4", {}).status_code == 403
    names = {t["name"] for t in _req("get", "/api/tools", tok, "t4").json()}
    assert "core.audit.list" not in names  # unauthorized tool not advertised
