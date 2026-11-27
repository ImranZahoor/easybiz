from datetime import timedelta

from django.utils import timezone
from django_tenants.utils import tenant_context

from easybiz.core.idempotency import service
from easybiz.core.idempotency.models import IdemKey

CALLER = "user:11111111-1111-1111-1111-111111111111"


def _hash(body=b"{}"):
    return service.request_hash("POST", "/api/core/roles", body)


def test_first_claim_is_fresh(synced, db_tenant):
    with tenant_context(db_tenant):
        assert service.claim(CALLER, "k1", "/api/core/roles", _hash()).kind == service.FRESH
        assert IdemKey.objects.get(key="k1").status == "in_progress"


def test_second_claim_while_in_progress_is_conflict(synced, db_tenant):
    with tenant_context(db_tenant):
        h = _hash()
        service.claim(CALLER, "k2", "/api/core/roles", h)
        assert service.claim(CALLER, "k2", "/api/core/roles", h).kind == service.CONFLICT


def test_completed_same_hash_replays(synced, db_tenant):
    with tenant_context(db_tenant):
        h = _hash()
        service.claim(CALLER, "k3", "/api/core/roles", h)
        service.finalize(CALLER, "k3", h, 201, '{"id": "x"}')
        c = service.claim(CALLER, "k3", "/api/core/roles", h)
        assert c.kind == service.REPLAY and c.response_status == 201 and c.body == '{"id": "x"}'


def test_same_key_different_payload_is_mismatch(synced, db_tenant):
    with tenant_context(db_tenant):
        service.claim(CALLER, "k4", "/api/core/roles", _hash(b'{"a": 1}'))
        service.finalize(CALLER, "k4", _hash(b'{"a": 1}'), 201, '{"id": "a"}')
        # same caller + key but a different body → different hash → mismatch, never a stale replay
        c = service.claim(CALLER, "k4", "/api/core/roles", _hash(b'{"a": 2}'))
        assert c.kind == service.MISMATCH


def test_different_caller_same_key_is_independent(synced, db_tenant):
    with tenant_context(db_tenant):
        h = _hash()
        service.claim(CALLER, "k5", "/api/core/roles", h)
        service.finalize(CALLER, "k5", h, 201, '{"id": "mine"}')
        # a different caller reusing the same key value gets their OWN fresh row, never a replay
        other = "user:22222222-2222-2222-2222-222222222222"
        assert service.claim(other, "k5", "/api/core/roles", h).kind == service.FRESH


def test_non_2xx_releases_the_key(synced, db_tenant):
    with tenant_context(db_tenant):
        h = _hash()
        service.claim(CALLER, "k6", "/api/core/roles", h)
        service.finalize(CALLER, "k6", h, 422, '{"detail": "no"}')
        assert not IdemKey.objects.filter(caller=CALLER, key="k6").exists()
        assert service.claim(CALLER, "k6", "/api/core/roles", h).kind == service.FRESH  # reusable


def test_expired_row_is_reclaimed(synced, db_tenant):
    with tenant_context(db_tenant):
        h = _hash()
        service.claim(CALLER, "k7", "/api/core/roles", h)
        IdemKey.objects.filter(key="k7").update(expires_at=timezone.now() - timedelta(minutes=1))
        c = service.claim(CALLER, "k7", "/api/core/roles", h)
        assert c.kind == service.FRESH  # expired row reclaimed as fresh
