from django.test import Client

from tests.test_core_modules_api import _token


def test_create_user_and_list(synced, provision, request):
    from easybiz.core.users.models import User

    request.addfinalizer(lambda: User.objects.filter(email="new@acme.test").delete())
    token = _token(provision)
    resp = Client().post(
        "/api/core/users",
        data={"email": "new@acme.test", "password": "change-me-now", "roles": ["owner"]},
        content_type="application/json",
        HTTP_HOST="acme.localhost",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    assert resp.status_code == 201
    emails = [
        u["email"]
        for u in Client()
        .get("/api/core/users", HTTP_HOST="acme.localhost", HTTP_AUTHORIZATION=f"Bearer {token}")
        .json()
    ]
    assert "new@acme.test" in emails


def test_new_user_without_password_422(synced, provision):
    token = _token(provision)
    resp = Client().post(
        "/api/core/users",
        data={"email": "np@acme.test", "roles": []},
        content_type="application/json",
        HTTP_HOST="acme.localhost",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    assert resp.status_code == 422


def test_cannot_delete_self(synced, provision):
    from easybiz.core.users.models import User

    token = _token(provision)
    owner = User.objects.get(email="owner@acme.test")
    resp = Client().delete(
        f"/api/core/users/{owner.id}",
        HTTP_HOST="acme.localhost",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    assert resp.status_code == 409


def test_delete_user_publishes_event(synced, provision, request):
    from django_tenants.utils import tenant_context

    from easybiz.core.events.models import OutboxEvent
    from easybiz.core.users import service as users
    from easybiz.core.users.models import User

    request.addfinalizer(lambda: User.objects.filter(email="temp@acme.test").delete())
    token = _token(provision)
    from easybiz.core.tenancy.models import Tenant

    acme = Tenant.objects.get(slug="acme")
    member = users.create_user("temp@acme.test", acme, password="change-me-now")
    resp = Client().delete(
        f"/api/core/users/{member.id}",
        HTTP_HOST="acme.localhost",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    assert resp.status_code == 204
    with tenant_context(acme):
        assert OutboxEvent.objects.filter(
            name="core.membership.removed", payload__user_id=str(member.id)
        ).exists()
