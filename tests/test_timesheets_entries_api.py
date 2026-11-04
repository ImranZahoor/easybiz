from django.test import Client
from django_tenants.utils import tenant_context

from easybiz.core.api.security import encode_tenant_token
from easybiz.core.iam import service as iam
from easybiz.core.users import service as users
from tests.test_timesheets_projects_api import _get, _post


def _setup(provision, slug):
    """Provision a timesheets tenant; return (tenant, owner_token)."""
    tenant = provision(slug=slug, modules=("timesheets",))
    owner = (
        Client()
        .post(
            "/api/auth/login",
            data={"email": f"owner@{slug}.test", "password": "change-me-now"},
            content_type="application/json",
            HTTP_HOST=f"{slug}.localhost",
        )
        .json()["access_token"]
    )
    return tenant, owner


def _add_user(tenant, email, roles):
    """Create a tenant member with the given roles; return (user, token)."""
    with tenant_context(tenant):
        u = users.create_user(email, tenant, password="change-me-now")
        iam.set_user_roles(u.id, roles)
    return u, encode_tenant_token(u.id, tenant.schema_name)


def _project(owner_token, slug, code="PRJ"):
    return _post(
        "/api/timesheets/projects", owner_token, {"code": code, "name": code}, slug=slug
    ).json()["id"]


def test_create_entry_requires_existing_project(synced, provision):
    tenant, owner = _setup(provision, "tse1")
    _, tok = _add_user(tenant, "u@tse1.test", ["timesheet_user"])
    r = _post(
        "/api/timesheets/entries",
        tok,
        {
            "project_id": "00000000-0000-0000-0000-000000000000",
            "work_date": "2026-11-03",
            "hours": "8.0",
        },
        slug="tse1",
    )
    assert r.status_code == 404


def test_create_entry_hours_bounds(synced, provision):
    tenant, owner = _setup(provision, "tse2")
    pid = _project(owner, "tse2")
    _, tok = _add_user(tenant, "u@tse2.test", ["timesheet_user"])
    for bad in ("0.0", "25.0"):
        r = _post(
            "/api/timesheets/entries",
            tok,
            {"project_id": pid, "work_date": "2026-11-03", "hours": bad},
            slug="tse2",
        )
        assert r.status_code == 422, bad
    ok = _post(
        "/api/timesheets/entries",
        tok,
        {"project_id": pid, "work_date": "2026-11-03", "hours": "8.0"},
        slug="tse2",
    )
    assert ok.status_code == 201 and ok.json()["status"] == "draft"


def test_visibility_own_vs_all(synced, provision):
    tenant, owner = _setup(provision, "tse3")
    pid = _project(owner, "tse3")
    ua, tok_a = _add_user(tenant, "a@tse3.test", ["timesheet_user"])
    ub, tok_b = _add_user(tenant, "b@tse3.test", ["timesheet_user"])
    _, tok_app = _add_user(tenant, "app@tse3.test", ["timesheet_approver"])
    body = {"project_id": pid, "work_date": "2026-11-03", "hours": "8.0"}
    _post("/api/timesheets/entries", tok_a, body, slug="tse3")
    _post("/api/timesheets/entries", tok_b, body, slug="tse3")

    assert len(_get("/api/timesheets/entries", tok_a, slug="tse3").json()) == 1  # own only
    assert len(_get("/api/timesheets/entries", tok_app, slug="tse3").json()) == 2  # approver: all
    filtered = _get(f"/api/timesheets/entries?user_id={ua.id}", tok_app, slug="tse3").json()
    assert len(filtered) == 1 and filtered[0]["user_id"] == str(ua.id)
    # a reader cannot peek at another user's entries via the filter
    assert len(_get(f"/api/timesheets/entries?user_id={ub.id}", tok_a, slug="tse3").json()) == 1


def test_submit_rules(synced, provision):
    tenant, owner = _setup(provision, "tse4")
    pid = _project(owner, "tse4")
    _, tok_a = _add_user(tenant, "a@tse4.test", ["timesheet_user"])
    _, tok_b = _add_user(tenant, "b@tse4.test", ["timesheet_user"])
    eid = _post(
        "/api/timesheets/entries",
        tok_a,
        {"project_id": pid, "work_date": "2026-11-03", "hours": "8.0"},
        slug="tse4",
    ).json()["id"]
    # another user cannot submit it
    assert _post(f"/api/timesheets/entries/{eid}/submit", tok_b, {}, slug="tse4").status_code == 404
    # owner-author submits: draft -> submitted
    assert (
        _post(f"/api/timesheets/entries/{eid}/submit", tok_a, {}, slug="tse4").json()["status"]
        == "submitted"
    )
    # re-submitting a submitted entry -> 409
    assert _post(f"/api/timesheets/entries/{eid}/submit", tok_a, {}, slug="tse4").status_code == 409
