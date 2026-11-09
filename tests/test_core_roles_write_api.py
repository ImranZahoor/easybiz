from django.test import Client
from django_tenants.utils import tenant_context

from easybiz.core.api.security import encode_tenant_token
from easybiz.core.events.models import OutboxEvent
from easybiz.core.iam import service as iam
from easybiz.core.iam.models import UserRole
from easybiz.core.tenancy.models import Tenant
from easybiz.core.users import service as users


def _owner(provision, slug):
    provision(slug=slug, modules=())
    tok = (
        Client()
        .post(
            "/api/auth/login",
            data={"email": f"owner@{slug}.test", "password": "change-me-now"},
            content_type="application/json",
            HTTP_HOST=f"{slug}.localhost",
        )
        .json()["access_token"]
    )
    return tok


def _req(method, path, token, slug, body=None):
    kw = {"HTTP_HOST": f"{slug}.localhost", "HTTP_AUTHORIZATION": f"Bearer {token}"}
    if body is not None:
        kw["data"] = body
        kw["content_type"] = "application/json"
    return getattr(Client(), method)(path, **kw)


def _limited_token(tenant, perms):
    """A user holding a role with exactly `perms` (so no `*`)."""
    with tenant_context(tenant):
        role = iam.create_role(tenant, "limited", perms, "")
        u = users.create_user("limited@x.test", tenant, password="change-me-now")
        UserRole.objects.create(user_id=u.id, role=role)
        return encode_tenant_token(u.id, tenant.schema_name)


def _role_id(slug, token, name):
    roles = _req("get", "/api/core/roles", token, slug).json()
    return next(r["id"] for r in roles if r["name"] == name)


def test_update_role_name_description_permissions(synced, provision):
    token = _owner(provision, "rw1")
    _req(
        "post",
        "/api/core/roles",
        token,
        "rw1",
        {"name": "viewer", "permissions": ["core.user.read"]},
    )
    rid = _role_id("rw1", token, "viewer")
    r = _req(
        "patch",
        f"/api/core/roles/{rid}",
        token,
        "rw1",
        {"description": "Read users", "permissions": ["core.user.read", "core.audit.read"]},
    )
    assert r.status_code == 200 and set(r.json()["permissions"]) == {
        "core.user.read",
        "core.audit.read",
    }


def test_define_time_escalation_blocked(synced, provision):
    token = _owner(provision, "rw2")
    limited = _limited_token(Tenant.objects.get(slug="rw2"), ["core.role.read", "core.role.manage"])
    # limited lacks core.user.manage -> cannot create a role granting it
    r = _req(
        "post",
        "/api/core/roles",
        limited,
        "rw2",
        {"name": "sneaky", "permissions": ["core.user.manage"]},
    )
    assert r.status_code == 422
    # owner (has *) can
    assert (
        _req(
            "post",
            "/api/core/roles",
            token,
            "rw2",
            {"name": "ok", "permissions": ["core.user.manage"]},
        ).status_code
        == 201
    )


def test_system_role_locked_except_description(synced, provision):
    token = _owner(provision, "rw3")
    rid = _role_id("rw3", token, "owner")  # the system owner role
    assert (
        _req(
            "patch", f"/api/core/roles/{rid}", token, "rw3", {"permissions": ["core.user.read"]}
        ).status_code
        == 422
    )
    assert (
        _req(
            "patch", f"/api/core/roles/{rid}", token, "rw3", {"description": "The boss"}
        ).status_code
        == 200
    )


def test_parent_cycle_rejected(synced, provision):
    token = _owner(provision, "rw4")
    _req("post", "/api/core/roles", token, "rw4", {"name": "a", "permissions": []})
    _req("post", "/api/core/roles", token, "rw4", {"name": "b", "permissions": []})
    bid = _role_id("rw4", token, "b")
    _req("patch", f"/api/core/roles/{bid}", token, "rw4", {"parent": "a"})  # b -> a
    aid = _role_id("rw4", token, "a")
    assert (
        _req("patch", f"/api/core/roles/{aid}", token, "rw4", {"parent": "b"}).status_code == 422
    )  # cycle


def test_delete_rules_and_events(synced, provision):
    token = _owner(provision, "rw5")
    oid = _role_id("rw5", token, "owner")
    assert _req("delete", f"/api/core/roles/{oid}", token, "rw5").status_code == 409  # system role
    _req(
        "post", "/api/core/roles", token, "rw5", {"name": "temp", "permissions": ["core.user.read"]}
    )
    tid = _role_id("rw5", token, "temp")
    assert _req("delete", f"/api/core/roles/{tid}", token, "rw5").status_code == 204
    with tenant_context(Tenant.objects.get(slug="rw5")):
        assert OutboxEvent.objects.filter(name="core.role.changed").exists()


def test_parent_change_cannot_escalate(synced, provision):
    _owner(provision, "rw7")
    tenant = Tenant.objects.get(slug="rw7")
    limited = _limited_token(tenant, ["core.role.read", "core.role.manage"])
    _req("post", "/api/core/roles", limited, "rw7", {"name": "r", "permissions": []})
    rid = _role_id("rw7", limited, "r")
    # a role-manager who lacks '*' cannot make a role inherit owner's '*' via parent
    assert (
        _req("patch", f"/api/core/roles/{rid}", limited, "rw7", {"parent": "owner"}).status_code
        == 422
    )


def test_clone_role(synced, provision):
    token = _owner(provision, "rw6")
    _req(
        "post", "/api/core/roles", token, "rw6", {"name": "src", "permissions": ["core.user.read"]}
    )
    sid = _role_id("rw6", token, "src")
    r = _req("post", f"/api/core/roles/{sid}/clone", token, "rw6", {"name": "copy"})
    assert r.status_code == 201 and r.json()["permissions"] == ["core.user.read"]
    assert (
        _req("post", f"/api/core/roles/{sid}/clone", token, "rw6", {"name": "copy"}).status_code
        == 422
    )  # dup
