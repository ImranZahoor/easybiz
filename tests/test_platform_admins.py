from easybiz.core.users.models import User
from tests.test_platform_auth_api import plat_delete, plat_get, plat_post


def _cleanup_users(request, *emails):
    request.addfinalizer(lambda: User.objects.filter(email__in=emails).delete())


def test_add_admin_new_requires_password(admin, request):
    _, token = admin
    _cleanup_users(request, "new@platform.test")
    assert (
        plat_post("/api/platform/admins", token, {"email": "new@platform.test"}).status_code == 422
    )
    assert (
        plat_post(
            "/api/platform/admins", token, {"email": "new@platform.test", "password": "short"}
        ).status_code
        == 422
    )
    r = plat_post(
        "/api/platform/admins", token, {"email": "new@platform.test", "password": "change-me-now"}
    )
    assert r.status_code == 201 and r.json()["email"] == "new@platform.test"
    assert User.objects.get(email="new@platform.test").is_platform_admin is True


def test_promote_existing_user_without_password(admin, request):
    _, token = admin
    _cleanup_users(request, "existing@platform.test")
    User.objects.create(email="existing@platform.test")  # plain user, no password
    r = plat_post("/api/platform/admins", token, {"email": "existing@platform.test"})
    assert r.status_code == 201
    assert User.objects.get(email="existing@platform.test").is_platform_admin is True


def test_remove_admin_guards(admin, request):
    me, token = admin
    _cleanup_users(request, "b@platform.test")
    plat_post(
        "/api/platform/admins", token, {"email": "b@platform.test", "password": "change-me-now"}
    )
    b = User.objects.get(email="b@platform.test")

    assert plat_delete(f"/api/platform/admins/{me.id}", token).status_code == 409  # self
    assert (
        plat_delete("/api/platform/admins/00000000-0000-0000-0000-000000000000", token).status_code
        == 404
    )
    assert plat_delete(f"/api/platform/admins/{b.id}", token).status_code == 204
    assert User.objects.get(id=b.id).is_platform_admin is False  # demoted

    from easybiz.core.tenancy.models import PlatformAuditLog

    actions = set(PlatformAuditLog.objects.values_list("action", flat=True))
    assert {"admin.added", "admin.removed"} <= actions


def test_list_admins(admin, request):
    _, token = admin
    emails = [a["email"] for a in plat_get("/api/platform/admins", token).json()]
    assert "admin@platform.test" in emails
