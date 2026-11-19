from datetime import timedelta

import pytest
from django.utils import timezone
from django_tenants.utils import tenant_context

from easybiz.core.iam import service as iam
from easybiz.core.iam.models import ApiKey

CREATOR = "11111111-1111-1111-1111-111111111111"


def test_create_returns_secret_once_and_hashes(synced, db_tenant):
    with tenant_context(db_tenant):
        key, secret = iam.create_api_key(
            "ci", ["core.audit.read"], creator_id=CREATOR, creator_perms={"core.audit.read"}
        )
        assert secret.startswith(key.prefix + ".")
        assert key.secret_hash != secret and len(key.secret_hash) == 64
        assert iam.authenticate_api_key(secret).id == key.id


def test_subset_rule_blocks_escalation(synced, db_tenant):
    with tenant_context(db_tenant):
        with pytest.raises(iam.ApiKeyError):
            iam.create_api_key(
                "ci", ["core.user.manage"], creator_id=CREATOR, creator_perms={"core.audit.read"}
            )


def test_revoked_key_does_not_authenticate(synced, db_tenant):
    with tenant_context(db_tenant):
        key, secret = iam.create_api_key("ci", [], creator_id=CREATOR, creator_perms=None)
        iam.revoke_api_key(key.id, actor_id=CREATOR)
        assert iam.authenticate_api_key(secret) is None


def test_expired_key_does_not_authenticate(synced, db_tenant):
    with tenant_context(db_tenant):
        key, secret = iam.create_api_key(
            "ci",
            [],
            creator_id=CREATOR,
            creator_perms=None,
            expires_at=timezone.now() - timedelta(seconds=1),
        )
        assert iam.authenticate_api_key(secret) is None


def test_malformed_and_wrong_secret_return_none(synced, db_tenant):
    with tenant_context(db_tenant):
        key, secret = iam.create_api_key("ci", [], creator_id=CREATOR, creator_perms=None)
        assert iam.authenticate_api_key("no-dot") is None
        assert iam.authenticate_api_key("unknownprefix.whatever") is None
        assert iam.authenticate_api_key(f"{key.prefix}.wrongsecret") is None


def test_authenticate_stamps_last_used(synced, db_tenant):
    with tenant_context(db_tenant):
        key, secret = iam.create_api_key("ci", [], creator_id=CREATOR, creator_perms=None)
        assert key.last_used_at is None
        iam.authenticate_api_key(secret)
        assert ApiKey.objects.get(id=key.id).last_used_at is not None
