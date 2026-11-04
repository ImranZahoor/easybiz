from django.test import Client


def _token(provision, slug="ts1"):
    provision(slug=slug, modules=("timesheets",))
    r = Client().post(
        "/api/auth/login",
        data={"email": f"owner@{slug}.test", "password": "change-me-now"},
        content_type="application/json",
        HTTP_HOST=f"{slug}.localhost",
    )
    return r.json()["access_token"]


def _post(path, token, body, slug="ts1"):
    return Client().post(
        path,
        data=body,
        content_type="application/json",
        HTTP_HOST=f"{slug}.localhost",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )


def _get(path, token, slug="ts1"):
    return Client().get(path, HTTP_HOST=f"{slug}.localhost", HTTP_AUTHORIZATION=f"Bearer {token}")


def test_create_project_uppercases_code(synced, provision):
    token = _token(provision)
    r = _post("/api/timesheets/projects", token, {"code": "alpha", "name": "Alpha"})
    assert r.status_code == 201 and r.json()["code"] == "ALPHA"


def test_duplicate_code_409(synced, provision):
    token = _token(provision, slug="ts2")
    _post("/api/timesheets/projects", token, {"code": "dup", "name": "A"}, slug="ts2")
    r = _post("/api/timesheets/projects", token, {"code": "DUP", "name": "B"}, slug="ts2")
    assert r.status_code == 409


def test_projects_listed_ordered_by_code(synced, provision):
    token = _token(provision, slug="ts3")
    _post("/api/timesheets/projects", token, {"code": "zeta", "name": "Z"}, slug="ts3")
    _post("/api/timesheets/projects", token, {"code": "amp", "name": "A"}, slug="ts3")
    codes = [p["code"] for p in _get("/api/timesheets/projects", token, slug="ts3").json()]
    assert codes == sorted(codes)
