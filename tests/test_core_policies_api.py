from django.db import connection
from django.test import Client
from django_tenants.utils import tenant_context

from easybiz.core.api.security import encode_tenant_token
from easybiz.core.iam import service as iam
from easybiz.core.iam.models import UserRole
from easybiz.core.tenancy.models import Tenant
from easybiz.core.users import service as users

GT = {"op": "gt", "left": {"var": "resource.hours"}, "right": {"var": "subject.approval_limit"}}


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


def _req(method, path, token, slug, body=None):
    kw = {"HTTP_HOST": f"{slug}.localhost", "HTTP_AUTHORIZATION": f"Bearer {token}"}
    if body is not None:
        kw["data"] = body
        kw["content_type"] = "application/json"
    return getattr(Client(), method)(path, **kw)


def _limited_token(tenant, perms):
    with tenant_context(tenant):
        role = iam.create_role(tenant, "limited", perms, "")
        u = users.create_user("limited@x.test", tenant, password="change-me-now")
        UserRole.objects.create(user_id=u.id, role=role)
        return encode_tenant_token(u.id, tenant.schema_name)


def test_requires_policy_manage(synced, provision):
    _owner(provision, "pol1")
    tenant = Tenant.objects.get(slug="pol1")
    tok = _limited_token(tenant, ["core.user.read"])
    assert _req("get", "/api/core/policies", tok, "pol1").status_code == 403


def test_create_and_evaluate_policy(synced, provision):
    token = _owner(provision, "pol2")
    r = _req(
        "post",
        "/api/core/policies",
        token,
        "pol2",
        {"permission": "timesheets.entry.approve", "effect": "deny_if", "condition": GT},
    )
    assert r.status_code == 201
    ev = _req(
        "post",
        "/api/core/policies/evaluate",
        token,
        "pol2",
        {
            "permission": "timesheets.entry.approve",
            "subject": {"approval_limit": 8},
            "resource": {"hours": 10},
        },
    )
    assert ev.status_code == 200 and ev.json()["allowed"] is False


def test_invalid_condition_is_422(synced, provision):
    token = _owner(provision, "pol3")
    r = _req(
        "post",
        "/api/core/policies",
        token,
        "pol3",
        {
            "permission": "timesheets.entry.approve",
            "effect": "deny_if",
            "condition": {"op": "regex", "left": {"var": "resource.x"}, "right": "a"},
        },
    )
    assert r.status_code == 422


def test_user_attributes_put_get(synced, provision):
    token = _owner(provision, "pol4")
    uid = _req("get", "/api/core/users", token, "pol4").json()[0]["id"]
    put = _req(
        "put",
        f"/api/core/users/{uid}/attributes",
        token,
        "pol4",
        {"attributes": {"approval_limit": 8}},
    )
    assert put.status_code == 200 and put.json()["attributes"] == {"approval_limit": 8}
    got = _req("get", f"/api/core/users/{uid}/attributes", token, "pol4")
    assert got.json()["attributes"] == {"approval_limit": 8}


def test_policies_are_tenant_isolated(synced, provision):
    a = _owner(provision, "pola")
    _req(
        "post",
        "/api/core/policies",
        a,
        "pola",
        {"permission": "timesheets.entry.approve", "effect": "deny_if", "condition": GT},
    )
    connection.set_schema_to_public()  # in-process HTTP left t_pola; provisioning needs public

    b = _owner(provision, "polb")
    assert _req("get", "/api/core/policies", b, "polb").json() == []
