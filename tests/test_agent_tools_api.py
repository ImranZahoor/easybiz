from django.test import Client
from django_tenants.utils import tenant_context

from easybiz.core.iam import service as iam
from easybiz.core.iam.models import Role, RolePermission, UserRole
from easybiz.core.tenancy.models import Tenant
from easybiz.core.users import service as users


def _owner(provision, slug):
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


def _make_user(tenant, perms, email):
    with tenant_context(tenant):
        role = Role.objects.create(name=f"r-{email}")
        RolePermission.objects.bulk_create([RolePermission(role=role, permission=p) for p in perms])
        u = users.create_user(email, tenant, password="change-me-now")
        UserRole.objects.create(user_id=u.id, role=role)
        return str(u.id)


def _req(method, path, token, slug, body=None):
    kw = {"HTTP_HOST": f"{slug}.localhost", "HTTP_AUTHORIZATION": f"Bearer {token}"}
    if body is not None:
        kw["data"] = body
        kw["content_type"] = "application/json"
    return getattr(Client(), method)(path, **kw)


def _mint(owner, slug, *, permissions, on_behalf, allowlist, scope):
    return _req(
        "post", "/api/core/apikeys", owner, slug,
        {"name": "agent", "permissions": permissions, "on_behalf_of_user": on_behalf,
         "tool_allowlist": allowlist, "scope": scope},
    ).json()["secret"]


def _ak(method, path, raw, slug, body=None):
    kw = {"HTTP_HOST": f"{slug}.localhost", "HTTP_AUTHORIZATION": f"ApiKey {raw}"}
    if body is not None:
        kw["data"] = body
        kw["content_type"] = "application/json"
    return getattr(Client(), method)(path, **kw)


def test_agent_key_invokes_read_tool_in_scope(synced, provision):
    owner = _owner(provision, "ag1")
    uid = _make_user(Tenant.objects.get(slug="ag1"), ["core.audit.read"], "u@ag1.test")
    raw = _mint(owner, "ag1", permissions=["core.audit.read"], on_behalf=uid,
                allowlist=["core.audit.list"], scope="read")
    assert _ak("post", "/api/tools/core.audit.list/invoke", raw, "ag1", {}).status_code == 200


def test_tool_not_in_allowlist_403(synced, provision):
    owner = _owner(provision, "ag2")
    uid = _make_user(Tenant.objects.get(slug="ag2"), ["core.audit.read"], "u@ag2.test")
    raw = _mint(owner, "ag2", permissions=["core.audit.read"], on_behalf=uid,
                allowlist=["core.audit.list"], scope="read")
    assert _ak("post", "/api/tools/core.context/invoke", raw, "ag2", {}).status_code == 403


def test_agent_key_read_scope_refused_write_tool(synced, provision):
    owner = _owner(provision, "ag3")
    uid = _make_user(Tenant.objects.get(slug="ag3"), ["timesheets.project.manage"], "u@ag3.test")
    raw = _mint(owner, "ag3", permissions=["timesheets.project.manage"], on_behalf=uid,
                allowlist=["timesheets.projects.create"], scope="read")
    assert _ak("post", "/api/tools/timesheets.projects.create/invoke", raw, "ag3",
               {"code": "abc", "name": "ABC"}).status_code == 403


def test_agent_key_write_scope_creates_project(synced, provision):
    owner = _owner(provision, "ag4")
    uid = _make_user(Tenant.objects.get(slug="ag4"), ["timesheets.project.manage"], "u@ag4.test")
    raw = _mint(owner, "ag4", permissions=["timesheets.project.manage"], on_behalf=uid,
                allowlist=["timesheets.projects.create"], scope="write")
    r = _ak("post", "/api/tools/timesheets.projects.create/invoke", raw, "ag4",
            {"code": "abc", "name": "ABC"})
    assert r.status_code == 200 and r.json()["code"] == "ABC"


def test_agent_key_lists_only_allowlisted(synced, provision):
    owner = _owner(provision, "ag5")
    uid = _make_user(Tenant.objects.get(slug="ag5"), ["core.audit.read"], "u@ag5.test")
    raw = _mint(owner, "ag5", permissions=["core.audit.read"], on_behalf=uid,
                allowlist=["core.audit.list"], scope="read")
    names = {t["name"] for t in _ak("get", "/api/tools", raw, "ag5").json()}
    assert names == {"core.audit.list"}


def test_service_key_without_onbehalf_rejected(synced, provision):
    owner = _owner(provision, "ag6")
    raw = _req("post", "/api/core/apikeys", owner, "ag6",
               {"name": "svc", "permissions": ["core.audit.read"]}).json()["secret"]
    assert _ak("get", "/api/tools", raw, "ag6").status_code == 401
