import json

from django.test import Client
from django_tenants.utils import tenant_context

from easybiz.core.tenancy.models import Tenant


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

    token = _owner(provision, "i3")
    body = json.dumps({"name": "role-z", "description": "", "permissions": []}).encode()
    with tenant_context(Tenant.objects.get(slug="i3")):
        h = service.request_hash("POST", "/api/core/roles", body, f"Bearer {token}")
        IdemKey.objects.create(
            key="key-3",
            endpoint="/api/core/roles",
            request_hash=h,  # matches the real request → reaches the in-progress check
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
