import json

from django.test import Client
from django_tenants.utils import tenant_context

from easybiz.core.tenancy.models import Tenant


def _owner(provision, slug):
    provision(slug=slug, modules=())
    return _login(slug)


def _login(slug):
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


def _create_role(token, slug, name, key=None):
    kw = {
        "HTTP_HOST": f"{slug}.localhost",
        "HTTP_AUTHORIZATION": f"Bearer {token}",
        "content_type": "application/json",
    }
    if key is not None:
        kw["HTTP_IDEMPOTENCY_KEY"] = key
    return Client().post(
        "/api/core/roles",
        data=json.dumps({"name": name, "description": "", "permissions": []}),
        **kw,
    )


def test_replay_returns_stored_response(synced, provision):
    token = _owner(provision, "i1")
    first = _create_role(token, "i1", "role-a", key="key-1")
    assert first.status_code == 201
    again = _create_role(token, "i1", "role-a", key="key-1")  # same key, same payload
    assert again.status_code == 201
    assert again.json() == first.json() and again["Idempotency-Replayed"] == "true"
    from easybiz.core.iam.models import Role

    with tenant_context(Tenant.objects.get(slug="i1")):
        assert Role.objects.filter(name="role-a").count() == 1  # created once


def test_same_user_second_token_still_replays(synced, provision):
    # the #1 fix: a retry after a token refresh (new token, same user) must replay, not 422
    token1 = _owner(provision, "i1b")
    first = _create_role(token1, "i1b", "role-r", key="key-1b")
    assert first.status_code == 201
    token2 = _login("i1b")  # a fresh login for the same user (idempotency keys on the user id)
    again = _create_role(token2, "i1b", "role-r", key="key-1b")
    assert again.status_code == 201 and again["Idempotency-Replayed"] == "true"


def test_same_key_different_payload_is_422(synced, provision):
    token = _owner(provision, "i2")
    _create_role(token, "i2", "role-x", key="key-2")
    r = _create_role(token, "i2", "role-y", key="key-2")  # same key, different body
    assert r.status_code == 422 and r.json()["code"] == "idempotency.payload_mismatch"


def test_in_progress_key_conflicts(synced, provision):
    from datetime import timedelta

    from django.utils import timezone

    from easybiz.core.idempotency import service
    from easybiz.core.idempotency.models import IdemKey
    from easybiz.core.users.models import User

    token = _owner(provision, "i3")
    caller = f"user:{User.objects.get(email='owner@i3.test').id}"
    body = json.dumps({"name": "role-z", "description": "", "permissions": []}).encode()
    with tenant_context(Tenant.objects.get(slug="i3")):
        h = service.request_hash("POST", "/api/core/roles", body)
        IdemKey.objects.create(
            caller=caller,
            key="key-3",
            endpoint="/api/core/roles",
            request_hash=h,  # matches the real caller + body → reaches the in-progress check
            status="in_progress",
            expires_at=timezone.now() + timedelta(hours=1),
        )
    r = _create_role(token, "i3", "role-z", key="key-3")  # a duplicate is mid-flight
    assert r.status_code == 409 and r.json()["code"] == "resource.conflict"


def test_error_response_is_not_cached(synced, provision):
    token = _owner(provision, "i4")
    _create_role(token, "i4", "dup", key="key-4")  # first create succeeds (201)
    bad = _create_role(token, "i4", "dup", key="key-5")  # duplicate name → 422 under a NEW key
    assert bad.status_code == 422
    from easybiz.core.idempotency.models import IdemKey

    with tenant_context(Tenant.objects.get(slug="i4")):
        assert not IdemKey.objects.filter(key="key-5").exists()  # released, reusable


def test_no_header_passes_through(synced, provision):
    token = _owner(provision, "i5")
    r = _create_role(token, "i5", "plain")  # no Idempotency-Key
    assert r.status_code == 201
    from easybiz.core.idempotency.models import IdemKey

    with tenant_context(Tenant.objects.get(slug="i5")):
        assert IdemKey.objects.count() == 0  # nothing recorded


def test_non_post_with_key_passes_through(synced, provision):
    token = _owner(provision, "i6")
    r = Client().get(
        "/api/core/roles",
        HTTP_HOST="i6.localhost",
        HTTP_AUTHORIZATION=f"Bearer {token}",
        HTTP_IDEMPOTENCY_KEY="key-6",
    )
    assert r.status_code == 200
    from easybiz.core.idempotency.models import IdemKey

    with tenant_context(Tenant.objects.get(slug="i6")):
        assert IdemKey.objects.count() == 0  # a GET never records


def test_unauthenticated_login_is_not_cached(synced, provision):
    # a login POST has no credential → caller unresolved → idempotency skipped → token never stored
    provision(slug="i7", modules=())
    r = Client().post(
        "/api/auth/login",
        data={"email": "owner@i7.test", "password": "change-me-now"},
        content_type="application/json",
        HTTP_HOST="i7.localhost",
        HTTP_IDEMPOTENCY_KEY="key-7",
    )
    assert r.status_code == 200
    from easybiz.core.idempotency.models import IdemKey

    with tenant_context(Tenant.objects.get(slug="i7")):
        assert IdemKey.objects.count() == 0  # login response (with its token) is not persisted


def test_secret_returning_endpoint_is_not_cached(synced, provision):
    # POST /api/core/apikeys returns the raw secret → never stored in idem_key (no secret at rest)
    token = _owner(provision, "i9")
    r = Client().post(
        "/api/core/apikeys",
        data=json.dumps({"name": "svc", "permissions": ["core.audit.read"]}),
        content_type="application/json",
        HTTP_HOST="i9.localhost",
        HTTP_AUTHORIZATION=f"Bearer {token}",
        HTTP_IDEMPOTENCY_KEY="key-9",
    )
    assert r.status_code == 201 and r.json()["secret"]  # created, secret returned
    from easybiz.core.idempotency.models import IdemKey

    with tenant_context(Tenant.objects.get(slug="i9")):
        assert IdemKey.objects.count() == 0  # the secret body was not persisted


def test_platform_plane_passthrough(synced):
    # the public/platform schema has no idem_key table — the header must not make it touch one
    r = Client().post(
        "/api/platform/auth/login",
        data={"email": "nobody@example.com", "password": "nope"},
        content_type="application/json",
        HTTP_HOST="localhost",
        HTTP_IDEMPOTENCY_KEY="key-8",
    )
    assert r.status_code == 401  # clean auth failure, not a 500 from a missing table
