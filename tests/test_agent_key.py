import pytest
from django_tenants.utils import tenant_context

from easybiz.core.iam import service as iam

CREATOR = "11111111-1111-1111-1111-111111111111"
USER = "22222222-2222-2222-2222-222222222222"


def test_create_agent_key_stores_scope_allowlist_user(synced, db_tenant):
    with tenant_context(db_tenant):
        key, _ = iam.create_api_key(
            db_tenant,
            "agent",
            ["core.audit.read"],
            creator_id=CREATOR,
            creator_perms={"*"},
            on_behalf_of_user=USER,
            tool_allowlist=["core.audit.list"],
            scope="write",
        )
        assert key.on_behalf_of_user is not None and key.scope == "write"
        assert key.tool_allowlist == ["core.audit.list"]


def test_create_rejects_unknown_permission(synced, db_tenant):
    with tenant_context(db_tenant):
        with pytest.raises(iam.ApiKeyError):
            iam.create_api_key(
                db_tenant, "k", ["made.up.perm"], creator_id=CREATOR, creator_perms={"*"}
            )


def test_create_rejects_bad_scope(synced, db_tenant):
    with tenant_context(db_tenant):
        with pytest.raises(iam.ApiKeyError):
            iam.create_api_key(
                db_tenant, "k", [], creator_id=CREATOR, creator_perms=None, scope="admin"
            )
