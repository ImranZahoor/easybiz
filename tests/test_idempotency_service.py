from datetime import timedelta

from django.utils import timezone
from django_tenants.utils import tenant_context

from easybiz.core.idempotency import service
from easybiz.core.idempotency.models import IdemKey


def _hash(body=b"{}", auth="Bearer a"):
    return service.request_hash("POST", "/api/core/roles", body, auth)


def test_first_claim_is_fresh(synced, db_tenant):
    with tenant_context(db_tenant):
        assert service.claim("k1", "/api/core/roles", _hash()).kind == service.FRESH
        assert IdemKey.objects.get(key="k1").status == "in_progress"


def test_second_claim_while_in_progress_is_conflict(synced, db_tenant):
    with tenant_context(db_tenant):
        h = _hash()
        service.claim("k2", "/api/core/roles", h)
        assert service.claim("k2", "/api/core/roles", h).kind == service.CONFLICT


def test_completed_same_hash_replays(synced, db_tenant):
    with tenant_context(db_tenant):
        h = _hash()
        service.claim("k3", "/api/core/roles", h)
        service.finalize("k3", 201, '{"id": "x"}')
        c = service.claim("k3", "/api/core/roles", h)
        assert c.kind == service.REPLAY and c.response_status == 201 and c.body == '{"id": "x"}'


def test_different_caller_same_key_is_mismatch(synced, db_tenant):
    with tenant_context(db_tenant):
        service.claim("k4", "/api/core/roles", _hash(auth="Bearer alice"))
        service.finalize("k4", 201, '{"id": "a"}')
        # bob reuses alice's key → different auth → different hash → mismatch, never a replay
        c = service.claim("k4", "/api/core/roles", _hash(auth="Bearer bob"))
        assert c.kind == service.MISMATCH


def test_non_2xx_releases_the_key(synced, db_tenant):
    with tenant_context(db_tenant):
        h = _hash()
        service.claim("k5", "/api/core/roles", h)
        service.finalize("k5", 422, '{"detail": "no"}')
        assert not IdemKey.objects.filter(key="k5").exists()
        assert service.claim("k5", "/api/core/roles", h).kind == service.FRESH  # reusable


def test_expired_row_is_reclaimed(synced, db_tenant):
    with tenant_context(db_tenant):
        h = _hash()
        service.claim("k6", "/api/core/roles", h)
        IdemKey.objects.filter(key="k6").update(expires_at=timezone.now() - timedelta(minutes=1))
        assert service.claim("k6", "/api/core/roles", h).kind == service.FRESH  # expired ⇒ fresh
