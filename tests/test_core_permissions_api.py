from tests.test_core_roles_write_api import _owner, _req


def test_role_detail_shows_parent_and_effective(synced, provision):
    token = _owner(provision, "pg1")
    _req(
        "post",
        "/api/core/roles",
        token,
        "pg1",
        {"name": "base", "permissions": ["core.audit.read"]},
    )
    _req(
        "post", "/api/core/roles", token, "pg1", {"name": "mgr", "permissions": ["core.user.read"]}
    )
    mid = next(
        r["id"] for r in _req("get", "/api/core/roles", token, "pg1").json() if r["name"] == "mgr"
    )
    _req("patch", f"/api/core/roles/{mid}", token, "pg1", {"parent": "base"})

    detail = _req("get", f"/api/core/roles/{mid}", token, "pg1").json()
    assert detail["parent"] == "base"
    assert detail["permissions"] == ["core.user.read"]  # own only
    assert set(detail["effective_permissions"]) == {
        "core.user.read",
        "core.audit.read",
    }  # + inherited


def test_role_detail_unknown_404(synced, provision):
    token = _owner(provision, "pg2")
    assert (
        _req(
            "get", "/api/core/roles/00000000-0000-0000-0000-000000000000", token, "pg2"
        ).status_code
        == 404
    )


def test_permissions_grouped_by_module(synced, provision):
    token = _owner(
        provision,
        "pg3",
    )
    groups = {g["module"]: g for g in _req("get", "/api/core/permissions", token, "pg3").json()}
    assert "core" in groups
    core_codes = {p["code"] for p in groups["core"]["permissions"]}
    assert {"core.user.read", "core.role.manage"} <= core_codes
    assert all(p.get("description") is not None for p in groups["core"]["permissions"])
    # a module not enabled for this tenant is absent
    assert "timesheets" not in groups
